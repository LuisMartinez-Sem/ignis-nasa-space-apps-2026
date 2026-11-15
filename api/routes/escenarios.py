"""Escenarios de reproducción del HUD: guiones evaluados con los modelos reales."""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel

from api.dependencias import obtener_catalogo, obtener_servicio
from src.escenarios import ErrorEscenario, Reproduccion, catalogo_escenarios, generar_reproduccion
from src.incidentes_historicos import CatalogoIncidentes
from src.servicio_modelos import ServicioModelos

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/escenarios", tags=["escenarios"])
IdEscenario = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,59}$", max_length=60)


class ResumenEscenario(BaseModel):
    id: str
    nombre: str
    descripcion: str
    duracion_s: float
    confianza: str
    grupo: str  # "escenario" | "incidente"


_INCIDENTES = {"mir-1997", "iss-2015", "apollo1-1967", "saffire-2016-2024"}


@router.get("", response_model=list[ResumenEscenario])
async def listar(catalogo: CatalogoIncidentes = Depends(obtener_catalogo)) -> list[ResumenEscenario]:
    """Guiones disponibles (escenarios genéricos e incidentes históricos)."""
    return [ResumenEscenario(id=e.id, nombre=e.nombre, descripcion=e.descripcion, duracion_s=e.duracion_s, confianza=e.confianza,
                             grupo="incidente" if e.id in _INCIDENTES else "escenario")
            for e in catalogo_escenarios(catalogo).values()]


@router.get("/{identificador}/reproduccion", response_model=Reproduccion)
async def reproduccion(
    request: Request, identificador: str = IdEscenario,
    catalogo: CatalogoIncidentes = Depends(obtener_catalogo), servicio: ServicioModelos = Depends(obtener_servicio),
) -> Reproduccion:
    """Frames a 1 Hz evaluados por RF/profundo y por el detector TCN; latencias medidas."""
    if servicio.predictor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo no disponible")
    try:
        escenario = catalogo_escenarios(catalogo)[identificador]
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Escenario desconocido: {identificador}") from error
    except ErrorEscenario as error:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(error)) from error
    cache: dict = getattr(request.app.state, "cache_escenarios", None) or {}
    request.app.state.cache_escenarios = cache
    clave = (identificador, servicio.detector is not None)
    if clave not in cache:
        cache[clave] = await asyncio.to_thread(generar_reproduccion, escenario, servicio.predictor, servicio.detector)
    return cache[clave]
