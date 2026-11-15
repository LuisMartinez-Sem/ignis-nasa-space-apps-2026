"""Estado y reporte de los modelos (RF, ensemble profundo, detector temporal)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencias import obtener_servicio
from src.entrenamiento import ReporteModelos, cargar_reporte
from src.servicio_modelos import ServicioModelos
from src.variables_pendientes import VARIABLES_NO_INCLUIDAS, VariablePendiente

router = APIRouter(prefix="/api/v1/modelo", tags=["modelo"])


@router.get("/estado")
async def estado(servicio: ServicioModelos = Depends(obtener_servicio)) -> dict:
    """Estado de cada componente y motores utilizables ahora mismo."""
    predictor = servicio.predictor
    return {
        "componentes": servicio.resumen(),
        "motores": predictor.motores_disponibles if predictor else [],
        "motor_defecto": predictor.motor_defecto if predictor else None,
        "detector_listo": servicio.detector is not None,
    }


@router.get("/reporte", response_model=ReporteModelos | None)
async def reporte(servicio: ServicioModelos = Depends(obtener_servicio)) -> ReporteModelos | None:
    """Métricas, calibración y latencia del último entrenamiento (None si no existe)."""
    return cargar_reporte(servicio.config.ruta_reporte)


@router.get("/variables_no_incluidas", response_model=list[VariablePendiente])
async def variables_no_incluidas() -> list[VariablePendiente]:
    """Roadmap público: qué variables físicas aún no modela IGNIS y por qué importan."""
    return list(VARIABLES_NO_INCLUIDAS)
