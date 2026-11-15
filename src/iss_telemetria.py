"""Telemetría SIMULADA de la atmósfera de la ISS (no es telemetría real) para probar la 'conexión' del frontend."""

from __future__ import annotations

import math
import random
import time

from pydantic import BaseModel

FUENTE = "Simulación IGNIS: valores plausibles de cabina de la ISS; NO es telemetría real"
PERIODO_S = 5400.0  # una órbita (~90 min): deriva térmica suave


class TelemetriaISS(BaseModel):
    t_unix: float
    simulado: bool = True
    fuente: str = FUENTE
    fraccion_o2: float
    presion_kpa: float
    temperatura_ambiente_k: float
    co2_ppm: float
    co_ppm: float
    humedad_pct: float


def telemetria_iss(t_unix: float | None = None) -> TelemetriaISS:
    """Lectura determinista por segundo (misma `t` → misma lectura): O₂≈20,9 %, P≈101,0 kPa (siempre ≤ 101,325: dentro del dominio del modelo), T≈295 K."""
    t = time.time() if t_unix is None else t_unix
    rng = random.Random(int(t))
    fase = 2 * math.pi * (t % PERIODO_S) / PERIODO_S
    return TelemetriaISS(
        t_unix=round(t, 3),
        fraccion_o2=round(0.209 + 0.0008 * math.sin(fase) + rng.gauss(0, 0.0003), 4),
        presion_kpa=round(101.0 + 0.15 * math.sin(fase / 2) + rng.gauss(0, 0.03), 2),
        temperatura_ambiente_k=round(295.0 + 0.8 * math.sin(fase) + rng.gauss(0, 0.05), 2),
        co2_ppm=round(3200 + 600 * math.sin(fase) + rng.gauss(0, 40), 0),
        co_ppm=round(max(0.0, 0.6 + rng.gauss(0, 0.1)), 2),
        humedad_pct=round(48 + 4 * math.sin(fase) + rng.gauss(0, 0.5), 1),
    )
