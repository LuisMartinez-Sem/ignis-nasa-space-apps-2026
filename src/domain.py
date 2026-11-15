"""Modelos de dominio compartidos entre ML y API (única fuente de verdad de rangos)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Material(StrEnum):
    """Combustibles sólidos de referencia (Saffire usa SIBAL)."""

    SIBAL = "sibal"  # mezcla algodón/fibra de vidrio, material de Saffire
    PMMA = "pmma"
    CELULOSA = "celulosa"  # algodón / papel


class RegimenFlujo(StrEnum):
    """Dirección del flujo respecto al avance de la llama.

    Concurrente = el flujo empuja la llama hacia combustible fresco: el caso
    peligroso en una nave (Saffire lo estudia). Opuesto = el flujo viene de frente.
    """

    OPUESTO = "opuesto"
    CONCURRENTE = "concurrente"


class NivelRiesgo(StrEnum):
    """Nivel discreto para el HUD; el índice continuo alimenta animaciones."""

    NOMINAL = "NOMINAL"
    PRECAUCION = "PRECAUCION"
    ALERTA = "ALERTA"
    CRITICO = "CRITICO"


class EstadoLlamaFria(StrEnum):
    """Estado de la detección de Cool Flame (invisible al ojo y a cámaras visibles)."""

    NO_EVALUADA = "NO_EVALUADA"  # sin lectura de temperatura de reacción
    INACTIVA = "INACTIVA"
    POSIBLE = "POSIBLE"
    PROBABLE = "PROBABLE"


class Motor(StrEnum):
    """Motores de predicción disponibles."""

    RF = "rf"  # Random Forest: rápido de entrenar, robusto con pocos datos
    PROFUNDO = "profundo"  # Ensemble de redes (PyTorch): incertidumbre y afinado


# Dominio OPERATIVO (validación de la API y del dataset): lo que el modelo está entrenado
# para evaluar. Revisión técnica externa:
# - O2: la ISS opera ~0,21-0,241; bajo 0,16 no hay combustión sostenida; 0,40 es el límite
#   de emergencia en atmósferas de baja presión.
# - Presión: máx. 101,325 kPa (atmósfera estándar). Un tope de 101,0 rechazaría la propia
#   atmósfera nominal de la ISS (101,3), por eso se usa el valor estándar. Mín. 35 kPa
#   (la Soyuz histórica operaba ~34 kPa).
RANGOS: dict[str, tuple[float, float]] = {
    "fraccion_o2": (0.16, 0.40),
    "velocidad_flujo_cm_s": (0.0, 100.0),
    "presion_kpa": (35.0, 101.325),
    "temperatura_ambiente_k": (250.0, 400.0),
    "espesor_combustible_mm": (0.01, 10.0),
    "temperatura_reaccion_k": (250.0, 2000.0),
}

# Dominio FÍSICO amplio: solo para reconstruir incidentes históricos (p. ej. Apollo 1 con O2
# puro a 115 kPa). Esas condiciones NO se evalúan con el modelo: se marcan fuera de dominio.
RANGOS_HISTORICOS: dict[str, tuple[float, float]] = {
    **RANGOS,
    "fraccion_o2": (0.10, 1.00),
    "presion_kpa": (20.0, 200.0),
}

# Aviso de extrapolación en el 10 % superior del O2 y por debajo de 40 kPa: aún es válido,
# pero el modelo tiene pocos datos cerca del borde y la confianza baja.
UMBRAL_ADVERTENCIA_O2 = 0.36
UMBRAL_ADVERTENCIA_PRESION_KPA = 40.0


class CondicionesAmbiente(BaseModel):
    """Estado del módulo y del combustible; entrada de toda predicción."""

    model_config = ConfigDict(extra="forbid")

    fraccion_o2: float = Field(
        ..., ge=RANGOS["fraccion_o2"][0], le=RANGOS["fraccion_o2"][1],
        description="Fracción molar de O2 (0.21 = aire).",
    )
    velocidad_flujo_cm_s: float = Field(
        ..., ge=RANGOS["velocidad_flujo_cm_s"][0], le=RANGOS["velocidad_flujo_cm_s"][1],
        description="Velocidad del flujo de ventilación sobre el combustible (cm/s).",
    )
    presion_kpa: float = Field(
        ..., ge=RANGOS["presion_kpa"][0], le=RANGOS["presion_kpa"][1],
        description="Presión total de la cabina (kPa).",
    )
    temperatura_ambiente_k: float = Field(
        ..., ge=RANGOS["temperatura_ambiente_k"][0], le=RANGOS["temperatura_ambiente_k"][1],
        description="Temperatura del gas ambiente (K).",
    )
    espesor_combustible_mm: float = Field(
        ..., ge=RANGOS["espesor_combustible_mm"][0], le=RANGOS["espesor_combustible_mm"][1],
        description="Espesor del combustible sólido (mm).",
    )
    material: Material = Field(..., description="Material del combustible.")
    regimen_flujo: RegimenFlujo = Field(
        default=RegimenFlujo.OPUESTO,
        description="Flujo opuesto o concurrente respecto al avance de la llama.",
    )
    temperatura_reaccion_k: float | None = Field(
        default=None,
        ge=RANGOS["temperatura_reaccion_k"][0], le=RANGOS["temperatura_reaccion_k"][1],
        description="Temperatura medida en la zona de reacción (termopar/IR). "
        "Habilita la evaluación de Cool Flames.",
    )


class CondicionesHistoricas(CondicionesAmbiente):
    """Condiciones de un incidente histórico: rangos físicos amplios (`RANGOS_HISTORICOS`).

    No es entrada de la API. Permite describir atmósferas que el modelo no cubre.
    """

    fraccion_o2: float = Field(..., ge=RANGOS_HISTORICOS["fraccion_o2"][0], le=RANGOS_HISTORICOS["fraccion_o2"][1])
    presion_kpa: float = Field(..., ge=RANGOS_HISTORICOS["presion_kpa"][0], le=RANGOS_HISTORICOS["presion_kpa"][1])


def advertencias_operativas(condiciones: CondicionesAmbiente) -> list[str]:
    """Avisos de confianza reducida cerca del borde del dominio operativo.

    Args:
        condiciones: condiciones a evaluar (ya validadas contra `RANGOS`).

    Returns:
        Lista de textos (vacía si la entrada está en la zona de confianza plena).
    """
    avisos: list[str] = []
    if condiciones.fraccion_o2 > UMBRAL_ADVERTENCIA_O2:
        avisos.append(
            f"Entrada cerca del límite operativo (O₂ = {condiciones.fraccion_o2:.2f} > "
            f"{UMBRAL_ADVERTENCIA_O2:.2f}). Confianza reducida: interpretar con precaución."
        )
    if condiciones.presion_kpa < UMBRAL_ADVERTENCIA_PRESION_KPA:
        avisos.append(
            f"Presión baja ({condiciones.presion_kpa:.1f} kPa < {UMBRAL_ADVERTENCIA_PRESION_KPA:.0f} kPa): "
            "pocos datos de entrenamiento en este borde. Confianza reducida."
        )
    return avisos


class FactorExplicativo(BaseModel):
    """Sensibilidad local del índice de riesgo a una variable de entrada."""

    variable: str
    valor: float
    efecto_indice: float = Field(
        ..., description="Cambio del índice (puntos) al aumentar la variable un 10 %."
    )
    efecto_velocidad_mm_s: float = Field(
        default=0.0, description="Cambio de la velocidad de propagación (mm/s) con ese +10 %."
    )
    direccion: Literal["sube", "baja", "neutro"]


class ResultadoEvaluacion(BaseModel):
    """Salida del predictor para una condición; contrato consumido por el HUD."""

    velocidad_propagacion_mm_s: float = Field(..., ge=0)
    incertidumbre_mm_s: float = Field(..., ge=0, description="Desv. estándar del motor (ensemble/árboles).")
    probabilidad_propagacion: float = Field(..., ge=0, le=1)
    probabilidad_llama_fria: float | None = Field(default=None, ge=0, le=1)
    estado_llama_fria: EstadoLlamaFria
    indice_riesgo: float = Field(..., ge=0, le=100)
    nivel_riesgo: NivelRiesgo
    acciones_sugeridas: list[str] = Field(
        default_factory=list,
        description="Apoyo a decisión; no sustituye los procedimientos de misión.",
    )
    origen_datos: str = Field(..., description="'sintetico' o 'real': procedencia del entrenamiento.")
    motor: str = Field(default="rf", description="Motor que produjo la predicción.")
    fuera_de_dominio: bool = Field(
        default=False, description="True si alguna entrada excede el rango de entrenamiento."
    )
    advertencias: list[str] = Field(default_factory=list)
    factores: list[FactorExplicativo] | None = Field(
        default=None, description="Explicabilidad local (solo si se solicita)."
    )
    latencia_ms: float = Field(default=0.0, ge=0, description="Tiempo de inferencia por condición.")
