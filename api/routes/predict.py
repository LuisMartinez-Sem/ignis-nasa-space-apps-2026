"""Endpoints de predicción de riesgo."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.dependencias import obtener_predictor
from api.schemas import InfoModelo, RespuestaLote, SolicitudLote
from src.domain import CondicionesAmbiente, FactorExplicativo, ResultadoEvaluacion
from src.model import VERSION_MODELO, ErrorModelo
from src.predictor import PredictorIgnis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["prediccion"])


def _motor_o_409(predictor: PredictorIgnis, motor: str | None) -> None:
    """Falla pronto con 409 si el motor pedido aún no está listo."""
    try:
        predictor.obtener_motor(motor)
    except ErrorModelo as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.post("/predict", response_model=ResultadoEvaluacion)
async def predecir(
    condiciones: CondicionesAmbiente,
    motor: str | None = Query(None, pattern=r"^[a-z]{2,12}$", description="rf | profundo"),
    explicar: bool = Query(False, description="Incluye sensibilidad local por variable."),
    predictor: PredictorIgnis = Depends(obtener_predictor),
) -> ResultadoEvaluacion:
    """Evalúa el riesgo de propagación para una condición del módulo."""
    _motor_o_409(predictor, motor)
    # CPU-bound: a un hilo para no bloquear el event loop
    return await asyncio.to_thread(lambda: predictor.evaluar(condiciones, motor=motor, explicar=explicar))


@router.post("/explain", response_model=list[FactorExplicativo])
async def explicar(
    condiciones: CondicionesAmbiente,
    motor: str | None = Query(None, pattern=r"^[a-z]{2,12}$"),
    predictor: PredictorIgnis = Depends(obtener_predictor),
) -> list[FactorExplicativo]:
    """Qué variable mueve más el riesgo ahora (sensibilidad local, no causal)."""
    _motor_o_409(predictor, motor)
    return await asyncio.to_thread(predictor.explicar, condiciones, motor=motor)


@router.post("/predict/batch", response_model=RespuestaLote)
async def predecir_lote(
    solicitud: SolicitudLote,
    motor: str | None = Query(None, pattern=r"^[a-z]{2,12}$"),
    predictor: PredictorIgnis = Depends(obtener_predictor),
) -> RespuestaLote:
    """Evalúa hasta 500 condiciones en una sola pasada vectorizada."""
    _motor_o_409(predictor, motor)
    resultados = await asyncio.to_thread(lambda: predictor.evaluar_lote(solicitud.condiciones, motor=motor))
    return RespuestaLote(resultados=resultados)


@router.get("/model/info", response_model=InfoModelo)
async def informacion_modelo(
    predictor: PredictorIgnis = Depends(obtener_predictor),
) -> InfoModelo:
    """Versión, procedencia de los datos y métricas de validación."""
    return InfoModelo(
        version=VERSION_MODELO,
        origen_datos=predictor.modelo.origen_datos,
        metricas=predictor.metricas,
    )
