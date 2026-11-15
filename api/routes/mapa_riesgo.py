"""Mapa de riesgo atmosférico (O₂ × presión) con entornos y evidencia experimental."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Request

from api.dependencias import obtener_predictor
from src.mapa_riesgo import MapaRiesgo, construir_cobertura, construir_mapa
from src.predictor import PredictorIgnis

router = APIRouter(prefix="/api/v1/mapa-riesgo", tags=["mapa-riesgo"])


@router.get("", response_model=MapaRiesgo)
async def mapa(request: Request, motor: str | None = Query(None, pattern=r"^[a-z]{2,12}$"), predictor: PredictorIgnis = Depends(obtener_predictor)) -> MapaRiesgo:
    """Rejilla 25×25 del índice de riesgo, con la posición de ISS/Luna/Marte/traje y la evidencia experimental conocida."""
    cache: dict = getattr(request.app.state, "cache_mapa", None) or {}
    request.app.state.cache_mapa = cache
    clave = (motor, id(predictor))
    if clave not in cache:
        cache[clave] = await asyncio.to_thread(construir_mapa, predictor, motor)
    cobertura, huella = construir_cobertura()  # dinámico: refleja la ingesta sin recalcular la rejilla
    return cache[clave].model_copy(update={"cobertura": cobertura, "huella": huella})
