"""Predictor IGNIS: fachada unificada sobre motores (RF / profundo) + Cool Flames + riesgo."""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd

from src.config import Configuracion
from src.cool_flame import clasificar_estado, probabilidad_llama_fria
from src.data_loader import cargar_dataset
from src.dataset_sintetico import FLUJO_PICO_CM_S
from src.domain import (
    RANGOS,
    advertencias_operativas,
    CondicionesAmbiente,
    EstadoLlamaFria,
    FactorExplicativo,
    NivelRiesgo,
    ResultadoEvaluacion,
)
from src.evaluacion import MetricasEntrenamiento
from src.model import ErrorModelo, ModeloPropagacion, MotorPrediccion
from src.modo_gas import CondicionesGas, ModeloGas, ResultadoGas

logger = logging.getLogger(__name__)

# Pesos del índice de riesgo: la probabilidad de propagar domina; la velocidad
# modula la severidad; la Cool Flame suma porque es invisible (riesgo oculto).
# Pesos del índice (revisión técnica): la velocidad pesa más porque dicta el tiempo de reacción
PESO_PROBABILIDAD = 0.55
PESO_VELOCIDAD = 0.30
PESO_LLAMA_FRIA = 0.15
# Velocidad de referencia de la severidad: tanh(1) = 0,76 a 10 mm/s; satura de forma suave
# Escala de la velocidad en el índice. Era 10 mm/s con la ley ilustrativa (referencia 8.0); al calibrar con Saffire-I
# la ley se redujo por 3.7905/8.0, y la normalización se reescala igual para conservar la semántica del índice.
VELOCIDAD_NORMALIZACION_MM_S = 4.74
# Fronteras de nivel sobre el índice 0–100: NOMINAL | PRECAUCION | ALERTA | CRITICO
FRONTERAS_NIVEL = np.array([25.0, 50.0, 75.0])
NIVELES: tuple[NivelRiesgo, ...] = (
    NivelRiesgo.NOMINAL, NivelRiesgo.PRECAUCION, NivelRiesgo.ALERTA, NivelRiesgo.CRITICO,
)
# Variables sobre las que se calcula la sensibilidad local (explicabilidad)
VARIABLES_EXPLICABLES: tuple[str, ...] = (
    "fraccion_o2", "velocidad_flujo_cm_s", "presion_kpa",
    "temperatura_ambiente_k", "espesor_combustible_mm", "temperatura_reaccion_k",
)
INCREMENTO_RELATIVO_EXPLICACION = 0.10
UMBRAL_EFECTO_NEUTRO = 0.05  # puntos de índice


def calcular_indice_riesgo(
    probabilidad_propagacion: np.ndarray,
    velocidad_mm_s: np.ndarray,
    probabilidad_llama_fria_o_nan: np.ndarray,
) -> np.ndarray:
    """Índice de riesgo 0–100 (vectorizado). NaN de Cool Flame cuenta como 0."""
    # tanh en lugar de min(): saturación física gradual (no un tope duro que iguale 10 y 100 mm/s)
    severidad = np.tanh(np.clip(velocidad_mm_s, 0.0, None) / VELOCIDAD_NORMALIZACION_MM_S)
    llama_fria = np.nan_to_num(probabilidad_llama_fria_o_nan, nan=0.0)
    indice = 100.0 * (
        PESO_PROBABILIDAD * probabilidad_propagacion
        + PESO_VELOCIDAD * severidad
        + PESO_LLAMA_FRIA * llama_fria
    )
    return np.clip(indice, 0.0, 100.0)


def clasificar_nivel(indice_riesgo: np.ndarray) -> list[NivelRiesgo]:
    """Convierte el índice continuo en nivel discreto para el HUD."""
    posiciones = np.digitize(indice_riesgo, FRONTERAS_NIVEL)
    return [NIVELES[int(p)] for p in posiciones]


def _acciones_sugeridas(
    nivel: NivelRiesgo,
    condiciones: CondicionesAmbiente,
    estado_llama_fria: EstadoLlamaFria,
) -> list[str]:
    """Reglas deterministas de apoyo a decisión (el copiloto LLM llega en v2)."""
    if nivel is NivelRiesgo.NOMINAL and estado_llama_fria is not EstadoLlamaFria.PROBABLE:
        return []
    acciones: list[str] = []
    if nivel in (NivelRiesgo.ALERTA, NivelRiesgo.CRITICO):
        acciones.append("Notificar al control de misión y seguir el procedimiento de incendio vigente.")
    if condiciones.velocidad_flujo_cm_s > FLUJO_PICO_CM_S * 1.5:
        acciones.append("Reducir la ventilación local: el flujo actual favorece la propagación.")
    if condiciones.fraccion_o2 > 0.25:
        acciones.append("Verificar fuentes de enriquecimiento de O2 en el módulo.")
    if estado_llama_fria in (EstadoLlamaFria.POSIBLE, EstadoLlamaFria.PROBABLE):
        acciones.append(
            "Posible llama fría invisible: confirmar con termografía antes de dar por extinguido el fuego."
        )
    if not acciones:
        acciones.append("Mantener vigilancia reforzada de temperatura y flujo.")
    return acciones


class PredictorIgnis:
    """Fachada de evaluación de riesgo sobre uno o más motores entrenados."""

    def __init__(self, modelo: MotorPrediccion) -> None:
        if not modelo.entrenado:
            raise ErrorModelo("PredictorIgnis requiere un modelo entrenado")
        self._motores: dict[str, MotorPrediccion] = {modelo.nombre: modelo}
        self.motor_defecto: str = modelo.nombre
        self._modelo_gas: ModeloGas | None = None  # modo gas (experimental): modelo aparte, nunca mezclado con el de sólidos

    def registrar_modelo_gas(self, modelo_gas: ModeloGas) -> None:
        """Activa el modo gas con un modelo de gases entrenado (el de sólidos no cambia)."""
        if not modelo_gas.entrenado:
            raise ErrorModelo("El modelo de gases no está entrenado")
        self._modelo_gas = modelo_gas

    # ---- gestión de motores -------------------------------------------------
    def registrar_motor(self, motor: MotorPrediccion) -> None:
        """Añade (o reemplaza) un motor entrenado."""
        if not motor.entrenado:
            raise ErrorModelo(f"El motor '{motor.nombre}' no está entrenado")
        self._motores[motor.nombre] = motor

    @property
    def motores_disponibles(self) -> list[str]:
        """Nombres de los motores registrados."""
        return list(self._motores)

    @property
    def modelo(self) -> MotorPrediccion:
        """Motor por defecto (compatibilidad con código que usa un único modelo)."""
        return self._motores[self.motor_defecto]

    @property
    def metricas(self) -> MetricasEntrenamiento | None:
        """Métricas de validación del motor por defecto."""
        return self.modelo.metricas

    def obtener_motor(self, nombre: str | None) -> MotorPrediccion:
        """Devuelve el motor pedido (o el de defecto).

        Raises:
            ErrorModelo: si el motor no está disponible.
        """
        clave = nombre or self.motor_defecto
        try:
            return self._motores[clave]
        except KeyError:
            raise ErrorModelo(
                f"Motor '{clave}' no disponible. Disponibles: {self.motores_disponibles}"
            ) from None

    # ---- evaluación ---------------------------------------------------------
    def _indices(self, datos: pd.DataFrame, motor: MotorPrediccion) -> np.ndarray:
        """Solo el índice de riesgo por fila (base de la explicabilidad)."""
        cruda = motor.predecir(datos)
        fria = probabilidad_llama_fria(
            datos["temperatura_reaccion_k"].astype(float).to_numpy(),
            datos["fraccion_o2"].to_numpy(), datos["presion_kpa"].to_numpy(),
        )
        return calcular_indice_riesgo(cruda.probabilidad_propagacion, cruda.velocidad_mm_s, fria)

    def evaluar(
        self, condiciones: CondicionesAmbiente | CondicionesGas, *, motor: str | None = None, explicar: bool = False,
        modo: str = "solido",
    ) -> ResultadoEvaluacion | ResultadoGas:
        """Evalúa una única condición; con `explicar=True` añade factores explicativos.

        `modo="solido"` (por defecto) usa el modelo actual, sin ningún cambio. `modo="gas"` (experimental) usa el modelo de gases y
        devuelve un `ResultadoGas` (ignición caliente y tiempo de quemado), no un índice de riesgo de sólidos.
        """
        if modo == "gas":
            if self._modelo_gas is None:
                raise ErrorModelo("Modo gas no disponible: ejecuta scripts/entrenar_gases.py y registra el modelo")
            if not isinstance(condiciones, CondicionesGas):
                raise ErrorModelo("El modo gas requiere CondicionesGas")
            return self._modelo_gas.predecir(condiciones)
        if modo != "solido":
            raise ErrorModelo(f"Modo desconocido: {modo!r} (solido | gas)")
        resultado = self.evaluar_lote([condiciones], motor=motor)[0]
        if explicar:
            resultado.factores = self.explicar(condiciones, motor=motor)
        return resultado

    def evaluar_lote(
        self, lote: list[CondicionesAmbiente], *, motor: str | None = None
    ) -> list[ResultadoEvaluacion]:
        """Evalúa varias condiciones con una sola pasada vectorizada del motor."""
        if not lote:
            return []
        motor_activo = self.obtener_motor(motor)
        datos = pd.DataFrame([c.model_dump(mode="json") for c in lote])

        inicio = time.perf_counter()
        cruda = motor_activo.predecir(datos)
        latencia_ms = (time.perf_counter() - inicio) * 1000.0 / len(lote)

        # None => NaN: la API distingue "no medido" de "probabilidad cero"
        temperatura = datos["temperatura_reaccion_k"].astype(float).to_numpy()
        prob_fria = probabilidad_llama_fria(
            temperatura, datos["fraccion_o2"].to_numpy(), datos["presion_kpa"].to_numpy()
        )
        indice = calcular_indice_riesgo(
            cruda.probabilidad_propagacion, cruda.velocidad_mm_s, prob_fria
        )
        niveles = clasificar_nivel(indice)
        fuera = motor_activo.envolvente.variables_fuera(datos)

        resultados: list[ResultadoEvaluacion] = []
        for i, condiciones in enumerate(lote):
            es_nan = bool(np.isnan(prob_fria[i]))
            estado = clasificar_estado(None if es_nan else float(prob_fria[i]))
            advertencias = [
                self._texto_extrapolacion(motor_activo, variable, float(datos.at[i, variable]))
                for variable in fuera[i]
            ] + advertencias_operativas(condiciones)
            resultados.append(
                ResultadoEvaluacion(
                    velocidad_propagacion_mm_s=float(cruda.velocidad_mm_s[i]),
                    incertidumbre_mm_s=float(cruda.incertidumbre_mm_s[i]),
                    probabilidad_propagacion=float(cruda.probabilidad_propagacion[i]),
                    probabilidad_llama_fria=None if es_nan else float(prob_fria[i]),
                    estado_llama_fria=estado,
                    indice_riesgo=float(indice[i]),
                    nivel_riesgo=niveles[i],
                    acciones_sugeridas=_acciones_sugeridas(niveles[i], condiciones, estado),
                    origen_datos=motor_activo.origen_datos,
                    motor=motor_activo.nombre,
                    fuera_de_dominio=bool(fuera[i]),
                    advertencias=advertencias,
                    latencia_ms=latencia_ms,
                )
            )
        return resultados

    @staticmethod
    def _texto_extrapolacion(motor: MotorPrediccion, variable: str, valor: float) -> str:
        """Mensaje legible de extrapolación para una variable."""
        limites = motor.envolvente.limites_de(variable)
        rango = f"[{limites[0]:.2f}, {limites[1]:.2f}]" if limites else "desconocido"
        return (
            f"Extrapolación: {variable}={valor:.3g} está fuera del rango de entrenamiento {rango}; "
            "la predicción no es fiable (el modelo tiende a saturar y subestimar)."
        )

    # ---- explicabilidad -----------------------------------------------------
    def explicar(
        self, condiciones: CondicionesAmbiente, *, motor: str | None = None
    ) -> list[FactorExplicativo]:
        """Sensibilidad local del índice: efecto de subir cada variable un 10 %.

        Una sola pasada vectorizada (1 + K filas). Es explicación local, no causal:
        responde "¿qué mueve más el riesgo AHORA?", útil para el copiloto.
        """
        motor_activo = self.obtener_motor(motor)
        base = condiciones.model_dump(mode="json")
        filas = [base]
        variables: list[str] = []
        for variable in VARIABLES_EXPLICABLES:
            valor = base.get(variable)
            if valor is None:
                continue  # p. ej. sin termopar: no hay nada que perturbar
            minimo, maximo = RANGOS[variable]
            # Paso mínimo del 1 % del rango: perturbar un valor 0 no puede ser nulo
            paso = max(abs(valor) * INCREMENTO_RELATIVO_EXPLICACION, 0.01 * (maximo - minimo))
            perturbada = dict(base)
            perturbada[variable] = float(min(maximo, valor + paso))
            filas.append(perturbada)
            variables.append(variable)

        indices = self._indices(pd.DataFrame(filas), motor_activo)
        factores: list[FactorExplicativo] = []
        for posicion, variable in enumerate(variables, start=1):
            valor = float(base[variable])
            paso_real = filas[posicion][variable] - valor
            # Se normaliza al +10 % para que las variables sean comparables entre sí
            escala = (abs(valor) * INCREMENTO_RELATIVO_EXPLICACION) / paso_real if paso_real else 0.0
            efecto = float(indices[posicion] - indices[0]) * min(1.0, escala) if escala else 0.0
            direccion = (
                "neutro" if abs(efecto) < UMBRAL_EFECTO_NEUTRO else ("sube" if efecto > 0 else "baja")
            )
            factores.append(
                FactorExplicativo(variable=variable, valor=valor, efecto_indice=efecto, direccion=direccion)
            )
        return sorted(factores, key=lambda f: abs(f.efecto_indice), reverse=True)


def cargar_o_entrenar_predictor(config: Configuracion) -> PredictorIgnis:
    """Carga el modelo RF guardado o lo entrena y persiste (arranque rápido de la API).

    Un modelo existente pero ilegible NO se sobrescribe en silencio: se reentrena
    y se avisa por log, para que el operador sepa que cambió.
    """
    if not config.reentrenar_al_iniciar:
        try:
            return PredictorIgnis(ModeloPropagacion.cargar(config.ruta_modelo))
        except ErrorModelo as error:
            logger.warning("No se pudo cargar el modelo; se reentrena", extra={"motivo": str(error)})

    datos, origen = cargar_dataset(
        config.ruta_dataset_csv, config.n_muestras_sinteticas, config.semilla_aleatoria
    )
    modelo = ModeloPropagacion(config.n_arboles, config.semilla_aleatoria)
    modelo.entrenar(datos, origen)
    try:
        modelo.guardar(config.ruta_modelo)
    except OSError:
        # Persistir es una optimización de arranque: no debe impedir servir
        logger.error("No se pudo guardar el modelo", exc_info=True)
    return PredictorIgnis(modelo)
