"""Análisis de Frontera de Pareto para priorización de experimentos (SI Dashboard)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query

from api.dependencias import obtener_predictor
from src.investigaciones import cargar_catalogo_con_estado
from src.pareto import EjeY, EntornoPareto, RespuestaPareto, construir_pareto
from src.predictor import PredictorIgnis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/investigaciones", tags=["investigaciones"])


@router.get("/pareto", response_model=RespuestaPareto)
async def pareto(
    entorno: EntornoPareto = Query("luna", description="Entorno objetivo con el que se infieren los campos desconocidos"),
    eje_y: EjeY = Query("riesgo", description="Eje vertical: riesgo del modelo, relevancia para el entorno o incertidumbre del riesgo"),
    motor: str | None = Query(None, pattern=r"^[a-z]{2,12}$"),
    predictor: PredictorIgnis = Depends(obtener_predictor),
) -> RespuestaPareto:
    """Dispersión riesgo × evidencia con la frontera de Pareto (alto riesgo, baja evidencia = más críticas).

    Se declara ANTES de `/{identificador}` en main (ver orden de registro) para que `pareto` no se confunda con un id.
    """
    _, estado = cargar_catalogo_con_estado()  # el catálogo nunca falla: ante un archivo roto sirve el respaldo
    logger.info("Pareto solicitado", extra={"entorno": entorno, "catalogo": estado.origen})
    return await asyncio.to_thread(construir_pareto, predictor, entorno, motor, eje_y)
