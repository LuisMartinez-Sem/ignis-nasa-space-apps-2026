"""Simulador de conexión con la ISS (telemetría simulada)."""

from __future__ import annotations

from fastapi import APIRouter

from src.iss_telemetria import TelemetriaISS, telemetria_iss

router = APIRouter(prefix="/api/v1/iss", tags=["iss"])


@router.get("/telemetria", response_model=TelemetriaISS)
async def telemetria() -> TelemetriaISS:
    """Última lectura simulada de la atmósfera de la ISS (`simulado: true`)."""
    return telemetria_iss()
