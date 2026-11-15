"""Middleware de seguridad y trazabilidad."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# CSP estricta: todo es del mismo origen (Three.js y fuentes están vendorizados).
# 'unsafe-inline' solo en estilos: Three/HUD ajustan estilos en línea; scripts sin inline.
CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class MiddlewareSeguridad(BaseHTTPMiddleware):
    """Cabeceras de seguridad, id de petición y tiempo de servicio."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        id_peticion = uuid.uuid4().hex[:12]
        inicio = time.perf_counter()
        respuesta = await call_next(request)
        duracion_ms = (time.perf_counter() - inicio) * 1000.0
        for nombre, valor in CABECERAS_SEGURIDAD.items():
            respuesta.headers.setdefault(nombre, valor)
        respuesta.headers["X-Request-Id"] = id_peticion
        respuesta.headers["Server-Timing"] = f"app;dur={duracion_ms:.1f}"
        if request.url.path.startswith("/api/") and duracion_ms > 500:
            logger.warning("Petición lenta", extra={"ruta": request.url.path, "ms": round(duracion_ms)})
        return respuesta
