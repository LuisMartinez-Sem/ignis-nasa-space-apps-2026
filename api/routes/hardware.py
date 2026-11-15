"""Estado del hardware físico (Arduino): el puente de Python envía un pulso y el HUD consulta si sigue vivo.

POST /api/v1/hardware/ping  → el puente registra «acabo de leer el sensor» (marca de tiempo global del proceso).
GET  /api/v1/hardware/ping  → {"conectado": bool, "dispositivo": str, "ultimo_dato_s": float | null}

`conectado` es true solo si el último pulso tiene ≤ 5 s. La marca vive en memoria del proceso: se pierde al reiniciar la API
(arranca desconectado) y no distingue entre varios dispositivos. No hay autenticación: es para la demo en red local.
"""

from __future__ import annotations

import logging
import threading
import time

from collections import deque
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/hardware", tags=["hardware"])

UMBRAL_CONEXION_S = 5.0
DISPOSITIVO_POR_DEFECTO = "Arduino R3"

_reloj = time.monotonic  # reloj monótono (no salta con cambios de hora del sistema); sustituible en pruebas
_cerrojo = threading.Lock()
_ultimo_pulso: float | None = None
_dispositivo: str = DISPOSITIVO_POR_DEFECTO
_ultima: dict | None = None
_historial: deque = deque(maxlen=120)  # (instante monótono, temperatura K): sirve la gráfica del HUD


class PulsoHardware(BaseModel):
    """Cuerpo (opcional) del pulso; solo identifica el dispositivo."""

    model_config = ConfigDict(extra="forbid")

    dispositivo: str = Field(DISPOSITIVO_POR_DEFECTO, min_length=1, max_length=40, pattern=r"^[\w .\-]+$")
    temperatura_k: float | None = Field(None, ge=250, le=2000, description="Última temperatura medida (K)")
    campo: Literal["ambiente", "reaccion"] | None = Field(None, description="Qué mide el sensor")
    indice_riesgo: float | None = Field(None, ge=0, le=100)
    nivel_riesgo: str | None = Field(None, pattern=r"^[A-Z]{3,12}$")


class LecturaHistorial(BaseModel):
    hace_s: float = Field(..., ge=0)
    temperatura_k: float


class UltimaLectura(BaseModel):
    temperatura_k: float
    campo: Literal["ambiente", "reaccion"] | None
    indice_riesgo: float | None
    nivel_riesgo: str | None


class EstadoHardware(BaseModel):
    conectado: bool
    dispositivo: str
    ultimo_dato_s: float | None = Field(None, ge=0, description="Segundos desde el último pulso; null si nunca hubo uno")


class DetalleHardware(EstadoHardware):
    """Estado + última medición e historial (para el panel del HUD); `/ping` conserva el contrato mínimo."""

    lectura: UltimaLectura | None = Field(None, description="Última medición enviada por el puente (si la hubo)")
    historial: list[LecturaHistorial] = Field(default_factory=list, description="Últimas lecturas (más antigua primero)")


def detalle_actual() -> DetalleHardware:
    """Estado calculado en el momento de la consulta (el paso del tiempo no requiere tareas en segundo plano)."""
    with _cerrojo:
        pulso, nombre, ultima, hist = _ultimo_pulso, _dispositivo, _ultima, list(_historial)
    if pulso is None:
        return DetalleHardware(conectado=False, dispositivo=nombre, ultimo_dato_s=None)
    ahora = _reloj()
    edad = max(0.0, ahora - pulso)
    return DetalleHardware(conectado=edad <= UMBRAL_CONEXION_S, dispositivo=nombre, ultimo_dato_s=round(edad, 1),
                           lectura=UltimaLectura(**ultima) if ultima else None,
                           historial=[LecturaHistorial(hace_s=round(max(0.0, ahora - t), 1), temperatura_k=k) for t, k in hist])


def estado_actual() -> EstadoHardware:
    d = detalle_actual()
    return EstadoHardware(conectado=d.conectado, dispositivo=d.dispositivo, ultimo_dato_s=d.ultimo_dato_s)


def reiniciar_estado() -> None:
    """Olvida el último pulso (pruebas)."""
    global _ultimo_pulso, _dispositivo, _ultima
    with _cerrojo:
        _ultimo_pulso, _dispositivo, _ultima = None, DISPOSITIVO_POR_DEFECTO, None
        _historial.clear()


@router.get("/ping", response_model=EstadoHardware)
async def consultar_ping() -> EstadoHardware:
    """¿Llegó un pulso del puente en los últimos 5 s?"""
    return estado_actual()


@router.get("/lectura", response_model=DetalleHardware)
async def consultar_lectura() -> DetalleHardware:
    """Estado, última medición e historial reciente del sensor (alimenta el panel de hardware del HUD)."""
    return detalle_actual()


@router.post("/ping", response_model=EstadoHardware)
async def registrar_ping(pulso: PulsoHardware | None = None) -> EstadoHardware:
    """El puente avisa que el sensor está vivo; guarda la marca de tiempo global y devuelve el estado resultante."""
    global _ultimo_pulso, _dispositivo, _ultima
    with _cerrojo:
        if _ultimo_pulso is None or _reloj() - _ultimo_pulso > UMBRAL_CONEXION_S:
            logger.info("Hardware conectado", extra={"dispositivo": (pulso or PulsoHardware()).dispositivo})
        _ultimo_pulso = _reloj()
        _dispositivo = (pulso or PulsoHardware()).dispositivo
        if pulso is not None and pulso.temperatura_k is not None:
            _ultima = {"temperatura_k": pulso.temperatura_k, "campo": pulso.campo, "indice_riesgo": pulso.indice_riesgo, "nivel_riesgo": pulso.nivel_riesgo}
            _historial.append((_reloj(), pulso.temperatura_k))
    return estado_actual()
