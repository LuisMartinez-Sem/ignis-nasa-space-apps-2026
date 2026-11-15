"""Dependencias compartidas de FastAPI."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from src.incidentes_historicos import CatalogoIncidentes
from src.predictor import PredictorIgnis
from src.servicio_modelos import ServicioModelos


def obtener_servicio(request: Request) -> ServicioModelos:
    """Servicio de modelos creado en el arranque (503 si aún no existe)."""
    servicio = getattr(request.app.state, "servicio", None)
    if servicio is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible")
    return servicio


def obtener_predictor(request: Request) -> PredictorIgnis:
    """Predictor listo (503 si el RF aún no cargó)."""
    predictor = obtener_servicio(request).predictor
    if predictor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo no disponible")
    return predictor


def obtener_catalogo(request: Request) -> CatalogoIncidentes:
    """Catálogo de incidentes históricos."""
    catalogo = getattr(request.app.state, "catalogo", None)
    if catalogo is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Catálogo no disponible")
    return catalogo
