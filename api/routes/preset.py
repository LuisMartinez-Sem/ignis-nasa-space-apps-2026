"""Presets de entorno: configura el modelo con la atmósfera esperada en la base lunar."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.dependencias import obtener_predictor
from src.domain import CondicionesAmbiente, Material, RegimenFlujo, ResultadoEvaluacion
from src.predictor import PredictorIgnis

router = APIRouter(prefix="/api/v1/preset", tags=["preset"])
PRESION_MAX_LUNA_KPA = 70.3  # 10,2 psi (reto NASA 2026): tope validado
PRESION_PRESET_KPA = 70.0  # valor del preset: cumple ≤ 70,3 y cae exacto en el slider del Monitor
O2_MIN_LUNA = 0.30


class PresetLunar(BaseModel):
    """Parámetros del preset; O₂ ≥ 30 % y presión ≤ 70,3 kPa se validan, el resto son supuestos editables."""

    model_config = ConfigDict(extra="forbid")

    fraccion_o2: float = Field(O2_MIN_LUNA, ge=O2_MIN_LUNA, le=0.40)
    presion_kpa: float = Field(PRESION_PRESET_KPA, ge=35.0, le=PRESION_MAX_LUNA_KPA)
    velocidad_flujo_cm_s: float = Field(10.0, ge=0, le=100)
    temperatura_ambiente_k: float = Field(295.0, ge=250, le=400)
    espesor_combustible_mm: float = Field(0.2, ge=0.01, le=10)
    material: Material = Material.SIBAL
    regimen_flujo: RegimenFlujo = RegimenFlujo.OPUESTO
    temperatura_reaccion_k: float | None = Field(None, ge=250, le=2000)


class ConfigMonitor(BaseModel):
    """Lo que el frontend inyecta TAL CUAL en el Monitor (modo manual): ids de sliders en sus unidades y contrato de la API."""

    modo: str = "manual"
    sliders: dict[str, float | bool]
    condiciones: dict[str, float | str | None]


class ResultadoPreset(BaseModel):
    monitor: ConfigMonitor
    condiciones: CondicionesAmbiente
    evaluacion: ResultadoEvaluacion
    referencia_iss: ResultadoEvaluacion
    delta_indice_vs_iss: float
    ppo2_kpa: float
    ppo2_iss_kpa: float
    explicacion: str = Field(..., description="Qué significa el índice del preset, en lenguaje llano")
    advertencias: list[str]
    supuestos: list[str]


def explicar_preset(delta: float) -> str:
    """Texto llano del índice del preset (el delta se calcula, nunca se escribe a mano).

    Args:
        delta: índice del preset menos el índice de la ISS, en puntos (puede ser negativo).
    """
    if abs(delta) < 0.05:
        comparacion = "0.0 pts, igual"
    else:
        comparacion = f"{'+' if delta > 0 else '-'}{abs(delta):.1f} pts"
    return f"Riesgo si hubiera ignición. No hay evento en curso. Comparado con la ISS ({comparacion})."


@router.post("/lunar", response_model=ResultadoPreset)
async def preset_lunar(parametros: PresetLunar | None = None, predictor: PredictorIgnis = Depends(obtener_predictor)) -> ResultadoPreset:
    """Evalúa la atmósfera de la base lunar (O₂ ≥ 30 %, P ≤ 70,3 kPa) y la compara con la ISS (21 %, 101,3 kPa)."""
    p = parametros or PresetLunar()
    cond = CondicionesAmbiente(**p.model_dump())
    iss = cond.model_copy(update={"fraccion_o2": 0.21, "presion_kpa": 101.3})
    ev, ref = predictor.evaluar(cond, explicar=True), predictor.evaluar(iss)
    termopar = cond.temperatura_reaccion_k is not None
    monitor = ConfigMonitor(
        sliders={"ctl-o2": round(cond.fraccion_o2 * 100, 1), "ctl-flujo": cond.velocidad_flujo_cm_s, "ctl-presion": cond.presion_kpa,
                 "ctl-temp": cond.temperatura_reaccion_k if termopar else 300.0, "ctl-termopar": termopar},
        condiciones={"fraccion_o2": cond.fraccion_o2, "velocidad_flujo_cm_s": cond.velocidad_flujo_cm_s, "presion_kpa": cond.presion_kpa,
                     "temperatura_ambiente_k": cond.temperatura_ambiente_k, "espesor_combustible_mm": cond.espesor_combustible_mm,
                     "material": cond.material.value, "temperatura_reaccion_k": cond.temperatura_reaccion_k})
    return ResultadoPreset(
        monitor=monitor, condiciones=cond, evaluacion=ev, referencia_iss=ref, delta_indice_vs_iss=round(ev.indice_riesgo - ref.indice_riesgo, 1),
        ppo2_kpa=round(cond.fraccion_o2 * cond.presion_kpa, 1), ppo2_iss_kpa=round(0.21 * 101.3, 1),
        explicacion=explicar_preset(round(ev.indice_riesgo - ref.indice_riesgo, 1)),
        advertencias=["El modelo se entrenó para MICROGRAVEDAD; la gravedad lunar (1/6 g) es parcial y PSI no tiene datos de gravedad parcial: el resultado es una extrapolación.",
                      "Modelo sintético calibrado con anclas publicadas (ajuste, no validación)."],
        supuestos=["La atmósfera (≥ 30 % O₂, ≤ 70,3 kPa) es la esperada según el reto, no una especificación final.",
                   "Flujo, material, espesor y temperatura son valores por defecto editables, no datos de una base real."])
