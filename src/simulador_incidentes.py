"""Simulador de incidentes históricos: cronología humana real vs. reacción de IGNIS.

Honestidad metodológica (decisión de diseño):
- NO se afirma "IGNIS fue N veces más rápido": no existe una medición humana comparable.
- Lo que se calcula es una *latencia de reacción de IGNIS* y se contrasta con la
  *ventana de oportunidad* documentada (tiempo durante el cual el evento seguía activo).
  Es un contrafactual, y cada resultado lo declara como tal.
- Cada entrada del timeline de IGNIS trae `confianza`: "modelo" (lo calcula el pipeline)
  o "ilustrativo" (entrada reconstruida por nosotros, no medida).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.domain import RANGOS, CondicionesAmbiente, CondicionesHistoricas, NivelRiesgo, ResultadoEvaluacion
from src.incidentes_historicos import (
    CategoriaEvento, Confianza, EventoHumano, Fuente, Incidente, TipoComparativa,
)
from src.predictor import PredictorIgnis
from src.senales import ESCALAS, FRECUENCIA_HZ, generar_secuencias
from src.trazas import racha_minima, traza_representativa

logger = logging.getLogger(__name__)

PASO_TELEMETRIA_S = 1.0
N_SECUENCIAS_FALSA_ALARMA = 200
SALTO_ESCALADA = 10.0  # puntos de índice sobre el valor inicial que cuentan como escalada
_VARIABLES_TELEMETRIA = (
    "fraccion_o2", "velocidad_flujo_cm_s", "presion_kpa", "temperatura_ambiente_k", "temperatura_reaccion_k",
)


class ErrorSimulacion(RuntimeError):
    """No se pudo simular (p. ej. detector no disponible y es imprescindible)."""


class EventoIgnis(BaseModel):
    """Hecho de la línea de tiempo de IGNIS."""

    t_s: float | None
    accion: str
    resultado: str = ""
    categoria: CategoriaEvento
    confianza: Confianza = "modelo"


class PuntoRiesgo(BaseModel):
    """Serie de riesgo para la gráfica (1 Hz)."""

    t_s: float
    indice_riesgo: float
    nivel: NivelRiesgo
    probabilidad_llama_fria: float | None = None


class Impacto(BaseModel):
    """Métricas contrafactuales; `metricas` es específico del tipo de incidente."""

    titulo: str
    resumen: str
    metricas: dict[str, float | str | bool | None]
    metodologia: str
    es_contrafactual: bool = True


class ComparativaIncidente(BaseModel):
    """Contrato de `GET /api/v1/incidentes/{id}/simular`."""

    id: str
    nombre: str
    tipo: TipoComparativa
    modelo_aplicable: bool
    fuera_de_dominio: bool = False
    advertencia_modelo: str | None
    duracion_s: float
    timeline_humano: list[EventoHumano]
    timeline_ignis: list[EventoIgnis]
    serie_riesgo: list[PuntoRiesgo] = Field(default_factory=list)
    serie_sensores: dict[str, list[float]] | None = None  # canales de la traza del detector
    frecuencia_sensores_hz: float | None = None
    impacto: Impacto
    supuestos: list[str]
    fuentes: list[Fuente]
    origen_datos_modelo: str


def _interpolar_telemetria(incidente: Incidente, duracion_s: float) -> pd.DataFrame:
    """Telemetría ilustrativa interpolada linealmente a `PASO_TELEMETRIA_S`."""
    base = incidente.condiciones_base
    assert base is not None
    t = np.arange(0.0, duracion_s + 1e-9, PASO_TELEMETRIA_S)
    columnas: dict[str, np.ndarray] = {}
    for variable in _VARIABLES_TELEMETRIA:
        puntos = [(p.t_s, getattr(p, variable)) for p in incidente.telemetria_ilustrativa
                  if getattr(p, variable) is not None]
        inicial = getattr(base, variable)
        if puntos:
            xs, ys = zip(*puntos)
            columnas[variable] = np.interp(t, xs, ys)
        elif inicial is not None:
            columnas[variable] = np.full_like(t, inicial)
        else:
            columnas[variable] = np.full_like(t, np.nan)
    return pd.DataFrame({"t_s": t, **columnas})


def _variables_fuera_de_dominio(base: CondicionesHistoricas) -> list[str]:
    """Textos de las variables que exceden el dominio operativo del modelo."""
    fuera: list[str] = []
    for variable, (minimo, maximo) in RANGOS.items():
        valor = getattr(base, variable, None)
        if valor is None:
            continue
        if not minimo <= valor <= maximo:
            fuera.append(f"{variable} = {valor:.3g} fuera de [{minimo:g}, {maximo:g}]")
    return fuera


def _condiciones_fila(base: CondicionesAmbiente, fila: pd.Series) -> CondicionesAmbiente:
    datos: dict[str, Any] = base.model_dump()
    for variable in _VARIABLES_TELEMETRIA:
        valor = fila[variable]
        datos[variable] = None if pd.isna(valor) else float(valor)
    return CondicionesAmbiente.model_validate(datos)


class SimuladorIncidentes:
    """Ejecuta la comparativa de un incidente con el predictor y (si hay) el detector."""

    def __init__(self, predictor: PredictorIgnis, detector: Any | None = None) -> None:
        self._predictor = predictor
        self._detector = detector  # DetectorTemporal | None (torch es opcional)

    # ------------------------------------------------------------------ API
    def simular(self, incidente: Incidente) -> ComparativaIncidente:
        """Despacha por tipo de comparativa.

        Raises:
            ErrorSimulacion: si falta un componente imprescindible.
        """
        despacho = {
            TipoComparativa.DETECCION_RESPUESTA: self._deteccion_respuesta,
            TipoComparativa.PRECONDICION: self._precondicion,
            TipoComparativa.FALSA_ALARMA: self._falsa_alarma,
            TipoComparativa.VALIDACION: self._validacion,
        }
        logger.info("Simulando incidente", extra={"id": incidente.id, "tipo": incidente.tipo.value})
        comparativa = despacho[incidente.tipo](incidente)
        comparativa.fuera_de_dominio = bool(incidente.fuera_de_dominio or comparativa.impacto.metricas.get("fuera_de_dominio"))
        return comparativa

    # ------------------------------------------------------------- helpers
    def _envolver(self, incidente: Incidente, *, timeline: list[EventoIgnis], impacto: Impacto,
                  duracion_s: float, serie: list[PuntoRiesgo] | None = None,
                  sensores: tuple[np.ndarray, float] | None = None) -> ComparativaIncidente:
        serie_sensores = None
        frecuencia = None
        if sensores is not None:
            canales = ("delta_t_k", "ir_rel", "luz_visible", "delta_o2_pct", "delta_p_kpa", "co_ppm")
            matriz, frecuencia = sensores
            serie_sensores = {c: np.round(matriz[:, i], 4).tolist() for i, c in enumerate(canales)}
        timeline.sort(key=lambda e: (e.t_s is None, e.t_s if e.t_s is not None else 0.0))
        return ComparativaIncidente(
            id=incidente.id, nombre=incidente.nombre, tipo=incidente.tipo,
            modelo_aplicable=incidente.modelo_aplicable, advertencia_modelo=incidente.advertencia_modelo,
            duracion_s=duracion_s, timeline_humano=incidente.timeline_humano, timeline_ignis=timeline,
            serie_riesgo=serie or [], serie_sensores=serie_sensores, frecuencia_sensores_hz=frecuencia,
            impacto=impacto, supuestos=incidente.supuestos_ignis, fuentes=incidente.fuentes,
            origen_datos_modelo=self._predictor.modelo.origen_datos,
        )

    def _serie_riesgo(self, base: CondicionesAmbiente, telemetria: pd.DataFrame
                      ) -> tuple[list[PuntoRiesgo], list[ResultadoEvaluacion]]:
        lote = [_condiciones_fila(base, fila) for _, fila in telemetria.iterrows()]
        resultados = self._predictor.evaluar_lote(lote)
        serie = [
            PuntoRiesgo(t_s=float(t), indice_riesgo=round(r.indice_riesgo, 1), nivel=r.nivel_riesgo,
                        probabilidad_llama_fria=r.probabilidad_llama_fria)
            for t, r in zip(telemetria["t_s"], resultados)
        ]
        return serie, resultados

    def _alarma_detector(self, tipo_traza: str, semilla: int
                         ) -> tuple[np.ndarray, float | None, float | None, float]:
        """Corre el detector en streaming; devuelve (señales, t_evento, t_alarma, latencia_ms_media)."""
        if self._detector is None:
            raise ErrorSimulacion("El detector temporal no está disponible (aún entrenando o sin torch)")
        traza = traza_representativa(tipo_traza, semilla)
        flujo = self._detector.streaming(traza.frecuencia_hz)
        t_alarma: float | None = None
        latencias: list[float] = []
        for muestra in traza.senales:
            paso = flujo.paso(muestra)
            latencias.append(paso.latencia_ms)
            if paso.alarma_nueva and t_alarma is None:
                t_alarma = paso.t_s
        return traza.senales, traza.t_inicio_s, t_alarma, float(np.mean(latencias))

    # ------------------------------------------------- detección y respuesta
    def _deteccion_respuesta(self, inc: Incidente) -> ComparativaIncidente:
        assert inc.condiciones_base and inc.traza_detector
        telemetria = _interpolar_telemetria(inc, inc.duracion_simulacion_s)
        serie, resultados = self._serie_riesgo(inc.condiciones_base, telemetria)
        senales, t_evento_traza, t_alarma_traza, lat_ms = self._alarma_detector(
            inc.traza_detector.tipo, inc.traza_detector.semilla)

        timeline: list[EventoIgnis] = [EventoIgnis(
            t_s=inc.inicio_evento_s, accion="Inicio del evento (referencia común de ambos timelines)",
            categoria="contexto", confianza="documentado")]
        latencia_detector_s: float | None = None
        if t_alarma_traza is not None and t_evento_traza is not None:
            latencia_detector_s = max(0.0, t_alarma_traza - t_evento_traza)
            timeline.append(EventoIgnis(
                t_s=round(inc.inicio_evento_s + latencia_detector_s, 2),
                accion="Detector temporal: ALARMA (3 votos consecutivos con P(evento) ≥ 0,60)",
                resultado=f"Latencia desde el inicio de la señal: {latencia_detector_s:.1f} s "
                          f"(traza sintética representativa; inferencia {lat_ms:.1f} ms/muestra).",
                categoria="deteccion"))
        else:
            timeline.append(EventoIgnis(
                t_s=None, accion="Detector temporal: sin alarma en la traza representativa",
                categoria="deteccion"))

        # Escalada = primer instante en que el índice SUBE respecto a su valor inicial.
        # Si la condición base ya parte alta no se cuenta como "reacción": sería trivial.
        indice_inicial = serie[0].indice_riesgo
        t_escalada: float | None = next(
            (p.t_s for p in serie if p.indice_riesgo >= indice_inicial + SALTO_ESCALADA), None)
        if t_escalada is not None:
            timeline.append(EventoIgnis(
                t_s=t_escalada,
                accion=f"El índice de riesgo sube {SALTO_ESCALADA:.0f} puntos sobre su valor inicial ({indice_inicial:.0f})",
                resultado="; ".join(resultados[int(t_escalada / PASO_TELEMETRIA_S)].acciones_sugeridas[:2]),
                categoria="respuesta"))
        timeline.append(EventoIgnis(
            t_s=0.0, accion="La telemetría usada es una reconstrucción cualitativa, no una medición",
            categoria="contexto", confianza="ilustrativo"))

        ventana = inc.ventana_humana_s
        t_primera = (inc.inicio_evento_s + latencia_detector_s if latencia_detector_s is not None
                     else t_escalada)
        reaccion_s = None if t_primera is None else round(t_primera - inc.inicio_evento_s, 2)
        metricas: dict[str, float | str | bool | None] = {
            "latencia_detector_s": None if latencia_detector_s is None else round(latencia_detector_s, 2),
            "t_escalada_riesgo_s": t_escalada,
            "reaccion_ignis_s": reaccion_s,
            "ventana_min_s": ventana[0] if ventana else None,
            "ventana_max_s": ventana[1] if ventana else None,
            "margen_ventana_min_s": None if (ventana is None or reaccion_s is None)
            else round(ventana[0] - reaccion_s, 2),
            "fraccion_ventana_consumida_pct": None if (ventana is None or reaccion_s is None)
            else round(100.0 * reaccion_s / ventana[1], 1),
        }
        if reaccion_s is not None and ventana:
            resumen = (f"IGNIS reaccionaría a los {reaccion_s:.1f} s; el fuego siguió activo entre "
                       f"{ventana[0]:.0f} y {ventana[1]:.0f} s. Quedarían ≥{ventana[0] - reaccion_s:.0f} s "
                       f"de margen para actuar (sin incluir el tiempo humano de ejecución).")
        else:
            resumen = "IGNIS no escaló dentro de la simulación; revisar el detector o los datos."
        impacto = Impacto(
            titulo="Ventana de oportunidad", resumen=resumen, metricas=metricas,
            metodologia=("Contrafactual: reacción de IGNIS (detector sobre una traza sintética + riesgo sobre "
                         "telemetría ilustrativa) contra la duración documentada del evento. No es una "
                         "medición ni un 'N veces más rápido'."))
        return self._envolver(inc, timeline=timeline, impacto=impacto, duracion_s=inc.duracion_simulacion_s,
                              serie=serie, sensores=(senales, FRECUENCIA_HZ))

    # --------------------------------------------------------- precondición
    def _indice_con_aire(self, base: CondicionesAmbiente) -> float | None:
        """Índice con la misma cabina pero aire normal (O₂ 21 %, 101,3 kPa); None si el modelo no puede evaluarlo."""
        try:
            aire = base.model_copy(update={"fraccion_o2": 0.21, "presion_kpa": 101.3, "velocidad_flujo_cm_s": max(base.velocidad_flujo_cm_s, 1.0)})
            return round(self._predictor.evaluar(CondicionesAmbiente.model_validate(aire.model_dump())).indice_riesgo, 1)
        except Exception:  # noqa: BLE001 (el dato es auxiliar: nunca debe tumbar la simulación)
            logger.warning("No se pudo calcular el índice con aire", exc_info=True)
            return None

    def _precondicion(self, inc: Incidente) -> ComparativaIncidente:
        """Riesgo de la atmósfera ANTES de la ignición.

        Si la atmósfera cae fuera del dominio operativo (`RANGOS`) NO se evalúa con el
        modelo: extrapolar a O2 = 100 % daría un número sin sentido físico. En su lugar se
        informa qué variables exceden el dominio y se aplica una regla fija de seguridad.
        """
        assert inc.condiciones_base
        base = inc.condiciones_base
        fuera = _variables_fuera_de_dominio(base)
        if fuera or not inc.modelo_aplicable:
            detalle = "; ".join(fuera) or "fuera del régimen del modelo (1 g)"
            timeline = [
                EventoIgnis(
                    t_s=0.0, accion="Atmósfera fuera del dominio operativo del modelo",
                    resultado=f"{detalle}. IGNIS no emite un índice: extrapolar daría un número sin base física.",
                    categoria="deteccion"),
                EventoIgnis(
                    t_s=0.0, accion="Regla fija de seguridad (no es predicción del modelo)",
                    resultado="O₂ por encima del límite operativo: no iniciar pruebas ni operaciones con ignitores "
                              "y verificar la atmósfera. Esta regla habría señalado la precondición del accidente.",
                    categoria="respuesta", confianza="supuesto"),
            ]
            impacto = Impacto(
                titulo="Fuera del dominio del modelo",
                resumen=("El modelo no evalúa esta atmósfera (" + detalle + "). La lección es la precondición: "
                         "una cabina con O₂ muy enriquecido convierte cualquier ignición en incendio."),
                metricas={"indice_riesgo": None, "indice_con_aire": self._indice_con_aire(base), "fuera_de_dominio": True,
                          "variables_fuera_de_dominio": detalle},
                metodologia="Comparación de la atmósfera documentada con el dominio operativo; no se simula el incendio.",
                es_contrafactual=False)
            return self._envolver(inc, timeline=timeline, impacto=impacto, duracion_s=inc.duracion_simulacion_s)

        condiciones = CondicionesAmbiente.model_validate(base.model_dump())
        real = self._predictor.evaluar(condiciones, explicar=True)
        timeline = [
            EventoIgnis(
                t_s=0.0, accion=f"Evaluación previa a la ignición con O2 = {base.fraccion_o2:.0%}",
                resultado=f"Índice {real.indice_riesgo:.0f}/100 ({real.nivel_riesgo.value}). " + " ".join(real.advertencias[:2]),
                categoria="deteccion"),
            EventoIgnis(
                t_s=0.0, accion="Acciones sugeridas", resultado="; ".join(real.acciones_sugeridas[:3]),
                categoria="respuesta"),
        ]
        factores = [f.variable for f in (real.factores or [])[:2]]
        impacto = Impacto(
            titulo="Riesgo de la atmósfera, antes del incendio",
            resumen=f"Índice {real.indice_riesgo:.0f}/100 ({real.nivel_riesgo.value}) con O₂ = {base.fraccion_o2:.0%}.",
            metricas={"indice_riesgo": round(real.indice_riesgo, 1), "indice_con_aire": self._indice_con_aire(base),
                      "nivel": real.nivel_riesgo.value,
                      "fuera_de_dominio": real.fuera_de_dominio, "factores_principales": ", ".join(factores) or None},
            metodologia="Evaluación del predictor sobre la atmósfera documentada; no simula el incendio.",
            es_contrafactual=False)
        return self._envolver(inc, timeline=timeline, impacto=impacto, duracion_s=inc.duracion_simulacion_s)

    # ---------------------------------------------------------- falsa alarma
    def _falsa_alarma(self, inc: Incidente) -> ComparativaIncidente:
        assert inc.condiciones_base and inc.traza_detector
        senales, _, t_alarma, lat_ms = self._alarma_detector(inc.traza_detector.tipo, inc.traza_detector.semilla)
        timeline = [
            EventoIgnis(t_s=inc.inicio_evento_s, accion="Pico aislado en un solo sensor (traza sintética)",
                        categoria="deteccion", confianza="ilustrativo"),
            EventoIgnis(
                t_s=None if t_alarma is None else round(t_alarma, 2),
                accion="IGNIS NO escala: sin consenso multicanal ni persistencia" if t_alarma is None
                else "IGNIS escaló ante el pico (falsa alarma)",
                resultado=f"Inferencia {lat_ms:.1f} ms/muestra.", categoria="respuesta"),
        ]
        # Tasa de falsas alarmas: detector vs. umbral ingenuo, sobre secuencias sintéticas negativas
        lote, _, meta = generar_secuencias(N_SECUENCIAS_FALSA_ALARMA * 6, semilla=4242)
        indices = np.flatnonzero(meta["tipo"].isin(["artefacto", "calentamiento", "nominal"]).to_numpy())
        indices = indices[:N_SECUENCIAS_FALSA_ALARMA]
        negativas = lote[indices]
        probs = self._detector.probabilidades(negativas)
        votos = (probs[..., 1] + probs[..., 2]) >= 0.60
        falsas_ignis = float(np.mean(racha_minima(votos, 3) >= 0))
        ingenuo = float(np.mean((np.abs(negativas / ESCALAS) > 0.5).any(axis=(1, 2))))
        impacto = Impacto(
            titulo="Discriminación de falsos positivos",
            resumen=(f"Sobre {len(indices)} secuencias sintéticas sin fuego: umbral simple de un canal "
                     f"dispara en {ingenuo:.0%}; IGNIS en {falsas_ignis:.0%}."),
            metricas={
                "n_secuencias": int(len(indices)), "falsas_alarmas_umbral_simple_pct": round(100 * ingenuo, 1),
                "falsas_alarmas_ignis_pct": round(100 * falsas_ignis, 1),
                "alarma_en_traza_del_incidente": t_alarma is not None,
            },
            metodologia=("Secuencias SINTÉTICAS (artefactos, calentamientos benignos, nominal). "
                         "El 'umbral simple' es una línea base nuestra (|canal/escala| > 0,5), no un "
                         "sistema real de la ISS."),
            es_contrafactual=False)
        return self._envolver(inc, timeline=timeline, impacto=impacto, duracion_s=inc.duracion_simulacion_s,
                              sensores=(senales, FRECUENCIA_HZ))

    # ------------------------------------------------------------ validación
    def _validacion(self, inc: Incidente) -> ComparativaIncidente:
        resultados = self._predictor.evaluar_lote([e.condiciones for e in inc.experimentos])
        timeline: list[EventoIgnis] = []
        errores: list[float] = []
        filas: list[str] = []
        for experimento, r in zip(inc.experimentos, resultados):
            texto = f"Predicción {r.velocidad_propagacion_mm_s:.2f} ± {r.incertidumbre_mm_s:.2f} mm/s"
            medida = experimento.medicion
            if medida:
                error = 100.0 * (r.velocidad_propagacion_mm_s - medida.velocidad_propagacion_mm_s) \
                    / max(medida.velocidad_propagacion_mm_s, 1e-9)
                errores.append(abs(error))
                texto += f" vs. medido {medida.velocidad_propagacion_mm_s:.2f} mm/s ({error:+.0f} %)"
                filas.append(f"{experimento.nombre}: {error:+.0f} %")
            else:
                texto += " (sin medición publicada en las fuentes consultadas)"
            if r.fuera_de_dominio:
                texto += " · EXTRAPOLACIÓN"
            timeline.append(EventoIgnis(
                t_s=None, accion=experimento.nombre, resultado=texto, categoria="deteccion",
                confianza="modelo"))
        n_con_medicion = len(errores)
        error_medio = float(np.mean(errores)) if errores else None
        impacto = Impacto(
            titulo="Brecha modelo vs. experimento",
            resumen=(f"Error absoluto medio {error_medio:.0f} % en {n_con_medicion} configuraciones con "
                     f"medición. Es la brecha que los datos PSI deben cerrar." if error_medio is not None
                     else "Sin mediciones publicadas para comparar."),
            metricas={"n_experimentos": len(inc.experimentos), "n_con_medicion": n_con_medicion,
                      "error_abs_medio_pct": None if error_medio is None else round(error_medio, 1),
                      "detalle": "; ".join(filas) or None},
            metodologia=("Modelo entrenado con datos sintéticos, evaluado en las condiciones de cada "
                         "experimento. Las mediciones de Saffire-I provienen de una presentación (confianza "
                         "media). No es validación del modelo final."),
            es_contrafactual=False)
        return self._envolver(inc, timeline=timeline, impacto=impacto, duracion_s=inc.duracion_simulacion_s)
