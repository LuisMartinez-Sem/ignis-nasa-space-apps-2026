"""Versiones del dataset (solo lectura; la ingesta se hace por CLI para controlar la procedencia)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.dependencias import obtener_servicio
from src.pipeline_datos import PATRON_ID_VERSION, VersionDataset, listar_versiones, obtener_version
from src.servicio_modelos import ServicioModelos
from src.data_loader import ErrorDatos

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/datos", tags=["datos"])


@router.get("/versiones", response_model=list[VersionDataset])
async def versiones(servicio: ServicioModelos = Depends(obtener_servicio)) -> list[VersionDataset]:
    """Snapshots versionados con su perfil y huecos de cobertura."""
    return await asyncio.to_thread(listar_versiones, servicio.config.directorio_datos)


@router.get("/versiones/{identificador}", response_model=VersionDataset)
async def version(
    identificador: str = Path(..., pattern=PATRON_ID_VERSION.pattern),
    servicio: ServicioModelos = Depends(obtener_servicio),
) -> VersionDataset:
    """Manifiesto de una versión."""
    try:
        return await asyncio.to_thread(obtener_version, servicio.config.directorio_datos, identificador)
    except ErrorDatos as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
