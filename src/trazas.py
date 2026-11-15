"""Selección determinista de trazas de sensores representativas (sin dependencia de torch).

El simulador de incidentes y el WebSocket de sensores necesitan "una traza de llama
caliente", "una de llama fría", etc. Se eligen del generador sintético con semilla
fija, de modo que la misma petición siempre devuelve la misma serie (reproducible).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.senales import FRECUENCIA_HZ, TIPOS_EVENTO, TIPOS_NEGATIVOS, generar_secuencias

N_CANDIDATAS = 400
INICIO_OBJETIVO_S = 8.0  # contexto previo suficiente para ver el "antes" del evento


class ErrorTraza(ValueError):
    """Tipo de evento desconocido o sin candidatas."""


@dataclass(frozen=True)
class TrazaSeleccionada:
    """Una serie (T, C) en unidades físicas y el instante real del evento (si lo hay)."""

    tipo: str
    senales: np.ndarray
    t_inicio_s: float | None
    frecuencia_hz: float = FRECUENCIA_HZ

    @property
    def duracion_s(self) -> float:
        """Duración total de la traza."""
        return self.senales.shape[0] / self.frecuencia_hz


def traza_representativa(tipo: str, semilla: int = 0) -> TrazaSeleccionada:
    """Elige una traza del `tipo` indicado.

    Para tipos con fuego se toma la candidata cuyo inicio está más cerca de
    `INICIO_OBJETIVO_S`; para tipos sin fuego, la primera candidata.

    Raises:
        ErrorTraza: si `tipo` no existe.
    """
    if tipo not in TIPOS_EVENTO:
        raise ErrorTraza(f"Tipo de traza desconocido: {tipo!r}. Válidos: {TIPOS_EVENTO}")
    senales, _, meta = generar_secuencias(N_CANDIDATAS, semilla=semilla + 777)
    candidatas = np.flatnonzero(meta["tipo"].to_numpy() == tipo)
    if candidatas.size == 0:  # improbable con 400 candidatas; se falla de forma explícita
        raise ErrorTraza(f"Sin candidatas del tipo {tipo!r} con la semilla {semilla}")
    if tipo in TIPOS_NEGATIVOS:
        elegida = int(candidatas[0])
        return TrazaSeleccionada(tipo, senales[elegida], None)
    inicios = meta["t_inicio_s"].to_numpy()[candidatas]
    elegida = int(candidatas[int(np.argmin(np.abs(inicios - INICIO_OBJETIVO_S)))])
    return TrazaSeleccionada(tipo, senales[elegida], float(meta["t_inicio_s"].iloc[elegida]))


def racha_minima(votos: np.ndarray, persistencia: int) -> np.ndarray:
    """Índice de la primera posición donde hay `persistencia` votos seguidos (o -1).

    Versión numpy pura (el módulo con torch no se importa aquí). `votos`: (n, T) bool.
    """
    votos = np.atleast_2d(votos)
    n, pasos = votos.shape
    if persistencia > pasos:
        return np.full(n, -1)
    acumulado = np.concatenate(
        [np.zeros((n, 1), dtype=np.int32), np.cumsum(votos, axis=1, dtype=np.int32)], axis=1
    )
    cumple = (acumulado[:, persistencia:] - acumulado[:, :-persistencia]) == persistencia
    primero = cumple.argmax(axis=1) + persistencia - 1
    return np.where(cumple.any(axis=1), primero, -1)
