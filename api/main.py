"""Punto de entrada FastAPI de IGNIS. Uso: `uvicorn api.main:app --reload`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.middleware import MiddlewareSeguridad
from api.routes import datos, emergencias, escenarios, hardware, incidentes, modelo, predict, si_insights, iss, investigaciones, mapa_riesgo, pareto, preset, confianza
from api.schemas import EstadoSalud
from api.websocket import LimiteConexiones, router as router_websocket
from src import __version__
from src.config import RAIZ_PROYECTO, obtener_configuracion
from src.incidentes_historicos import CatalogoIncidentes
from src.servicio_modelos import ServicioModelos
from src.utils import configurar_logging

logger = logging.getLogger(__name__)

DIRECTORIO_FRONTEND = RAIZ_PROYECTO / "frontend"


@asynccontextmanager
async def ciclo_vida(app: FastAPI) -> AsyncIterator[None]:
    """Carga el RF (bloqueante) y el deep learning/detector en segundo plano.

    La API responde en cuanto el RF está listo; el HUD consulta `/api/v1/modelo/estado`.
    """
    config = obtener_configuracion()
    configurar_logging(config.nivel_log)
    logger.info("Iniciando IGNIS", extra={"entorno": config.entorno, "version": __version__})
    servicio = ServicioModelos(config)
    app.state.servicio = servicio
    app.state.catalogo = CatalogoIncidentes()
    app.state.limite_ws = LimiteConexiones(config.max_conexiones_ws)
    await servicio.iniciar(esperar_opcionales=config.esperar_modelos_opcionales)
    yield
    await servicio.detener()
    logger.info("IGNIS detenido")


def crear_app() -> FastAPI:
    """Fábrica de la aplicación (permite configuraciones distintas en tests)."""
    config = obtener_configuracion()
    app = FastAPI(
        title="IGNIS API",
        description="Intelligent Guidance for Ignition & Suppression — riesgo de incendio en microgravedad.",
        version=__version__,
        lifespan=ciclo_vida,
    )
    # Orígenes explícitos, sin credenciales ni comodines: superficie mínima
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.origenes_cors,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(MiddlewareSeguridad)
    for router in (predict.router, incidentes.router, escenarios.router, emergencias.router, si_insights.router, iss.router, hardware.router, pareto.router, confianza.router, investigaciones.router, mapa_riesgo.router, preset.router, modelo.router, datos.router, router_websocket):
        app.include_router(router)

    @app.get("/health", response_model=EstadoSalud, tags=["sistema"])
    async def salud() -> EstadoSalud:
        """Sonda de vida y resumen de disponibilidad."""
        servicio: ServicioModelos | None = getattr(app.state, "servicio", None)
        catalogo: CatalogoIncidentes | None = getattr(app.state, "catalogo", None)
        predictor = None if servicio is None else servicio.predictor
        return EstadoSalud(
            estado="ok", modelo_cargado=predictor is not None, version=__version__,
            componentes={} if servicio is None else {k: v.value for k, v in servicio.estado.items()},
            motores=[] if predictor is None else predictor.motores_disponibles,
            incidentes=0 if catalogo is None else len(catalogo.listar()),
        )

    # El HUD se sirve desde el mismo origen (WebSocket sin CORS). Se monta al final:
    # "/" captura todo lo que no coincidió con una ruta de la API.
    if (DIRECTORIO_FRONTEND / "index.html").is_file():
        app.mount("/", StaticFiles(directory=DIRECTORIO_FRONTEND, html=True), name="frontend")
    else:
        logger.warning("No se encontró frontend/index.html; solo se sirve la API")

    return app


app = crear_app()
