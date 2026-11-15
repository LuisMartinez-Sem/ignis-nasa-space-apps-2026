"""Informe de confianza por investigación (JSON y PDF)."""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from api.dependencias import obtener_predictor
from src.confianza import InformeConfianza, construir_informe, informe_pdf
from src.investigaciones import ENTORNOS, obtener
from src.predictor import PredictorIgnis

router = APIRouter(prefix="/api/v1/investigaciones", tags=["investigaciones"])
IdInv = Path(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,59}$")


async def _informe(identificador: str, entorno: str, predictor: PredictorIgnis) -> InformeConfianza:
    inv = obtener(identificador)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe la investigación '{identificador}'")
    if entorno not in ENTORNOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Entorno desconocido: {entorno}")
    return await asyncio.to_thread(construir_informe, predictor, inv, entorno)


@router.get("/{identificador}/confianza", response_model=InformeConfianza)
async def confianza(identificador: str = IdInv, entorno: str = Query("luna", pattern=r"^[a-z]{2,12}$"), predictor: PredictorIgnis = Depends(obtener_predictor)) -> InformeConfianza:
    """Cuánto respaldo tiene el riesgo asignado: entradas verificadas/inferidas/supuestas, factores y sensibilidad."""
    return await _informe(identificador, entorno, predictor)


@router.get("/{identificador}/confianza.pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
async def confianza_pdf(identificador: str = IdInv, entorno: str = Query("luna", pattern=r"^[a-z]{2,12}$"), predictor: PredictorIgnis = Depends(obtener_predictor)) -> Response:
    """Informe de confianza en PDF de una página."""
    inf = await _informe(identificador, entorno, predictor)
    nombre = re.sub(r"[^A-Za-z0-9_-]+", "_", inf.id)
    return Response(content=await asyncio.to_thread(informe_pdf, inf), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="confianza_{nombre}.pdf"', "Cache-Control": "no-store"})
