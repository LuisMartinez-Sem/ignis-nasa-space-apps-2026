"""Benchmark de detección: IGNIS (TCN) vs. umbral térmico vs. cámara visible.

Mide lo que importa a un operador: ¿qué fracción de fuegos detecta?, ¿en cuántos
segundos?, ¿cuántas falsas alarmas por hora? Para que la comparación sea justa
se incluye un umbral térmico *calibrado* al mismo nivel de falsas alarmas que IGNIS
(el baseline más fuerte que se puede construir con un solo canal).

TODO el benchmark corre sobre señales sintéticas (`senales.py`): demuestra la
mecánica y la latencia, NO sustituye la validación con datos reales de FLEX/BASS.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
import pandas as pd
from pydantic import BaseModel

from src.detector_temporal import (
    MUESTRAS_PERSISTENCIA,
    UMBRAL_ALARMA,
    DetectorTemporal,
    primera_alarma,
)
from src.senales import FRECUENCIA_HZ, TIPOS_NEGATIVOS, Clase, generar_secuencias

logger = logging.getLogger(__name__)

TIPOS_CON_FUEGO: tuple[str, ...] = ("fria", "fria_a_caliente", "caliente")
UMBRAL_TERMICO_FIJO_K = 30.0
PERSISTENCIA_TERMICA = 5
UMBRAL_LUZ_VISIBLE = 0.15
PERSISTENCIA_LUZ = 3
BARRIDO_UMBRALES_K = np.arange(5.0, 400.0, 2.5)


class EstadisticaTipo(BaseModel):
    """Resultado de un método sobre un tipo de evento."""

    n_eventos: int
    tasa_deteccion: float
    ttd_mediana_s: float | None
    ttd_p90_s: float | None


class ResultadoMetodo(BaseModel):
    """Desempeño de un método de detección."""

    nombre: str
    descripcion: str
    por_tipo: dict[str, EstadisticaTipo]
    falsas_alarmas_por_hora: float
    tasa_deteccion_global: float


class InformeBenchmark(BaseModel):
    """Informe completo, serializable para la API y el HUD."""

    n_secuencias: int
    duracion_s: float
    frecuencia_hz: float
    metodos: list[ResultadoMetodo]
    latencia_inferencia_ms_p50: float
    latencia_inferencia_ms_p95: float
    origen_datos: str = "sintetico"
    nota: str = (
        "Señales sintéticas: valida la mecánica y la latencia, no la física real. "
        "Recalibrar con series de FLEX/BASS."
    )


def alarma_umbral(valores: np.ndarray, umbral: float, persistencia: int) -> np.ndarray:
    """Índice de la primera alarma de un detector de umbral con persistencia (o -1)."""
    return primera_alarma(valores >= umbral, persistencia)


def _evaluar_alarmas(
    indices_alarma: np.ndarray, meta: pd.DataFrame, frecuencia_hz: float, pasos: int
) -> tuple[dict[str, EstadisticaTipo], float, float]:
    """Convierte índices de primera alarma en estadísticas por tipo y falsas alarmas/hora."""
    tipo = meta["tipo"].to_numpy()
    inicio_idx = np.floor(meta["t_inicio_s"].to_numpy() * frecuencia_hz)  # NaN si no hay fuego
    hay_alarma = indices_alarma >= 0

    # Falsa alarma: sin fuego en absoluto, o alarma ANTES del inicio real
    sin_fuego = np.isin(tipo, list(TIPOS_NEGATIVOS))
    prematura = ~sin_fuego & hay_alarma & (indices_alarma < np.nan_to_num(inicio_idx, nan=np.inf))
    falsas = (sin_fuego & hay_alarma) | prematura
    # Horas sin fuego: secuencias negativas completas + tramo previo al inicio en las demás
    pasos_sin_fuego = np.where(sin_fuego, pasos, np.nan_to_num(inicio_idx, nan=0.0))
    horas_sin_fuego = pasos_sin_fuego.sum() / frecuencia_hz / 3600.0
    falsas_por_hora = float(falsas.sum() / horas_sin_fuego) if horas_sin_fuego > 0 else 0.0

    por_tipo: dict[str, EstadisticaTipo] = {}
    detectados = 0
    total_eventos = 0
    for nombre in TIPOS_CON_FUEGO:
        mascara = tipo == nombre
        n = int(mascara.sum())
        if n == 0:
            continue
        valido = mascara & hay_alarma & ~prematura
        ttd = (indices_alarma[valido] - inicio_idx[valido]) / frecuencia_hz
        detectados += int(valido.sum())
        total_eventos += n
        por_tipo[nombre] = EstadisticaTipo(
            n_eventos=n,
            tasa_deteccion=float(valido.sum() / n),
            ttd_mediana_s=float(np.median(ttd)) if ttd.size else None,
            ttd_p90_s=float(np.percentile(ttd, 90)) if ttd.size else None,
        )
    tasa_global = detectados / total_eventos if total_eventos else 0.0
    return por_tipo, falsas_por_hora, float(tasa_global)


def _resultado(
    nombre: str, descripcion: str, indices: np.ndarray, meta: pd.DataFrame, hz: float, pasos: int
) -> ResultadoMetodo:
    por_tipo, falsas, tasa = _evaluar_alarmas(indices, meta, hz, pasos)
    return ResultadoMetodo(
        nombre=nombre, descripcion=descripcion, por_tipo=por_tipo,
        falsas_alarmas_por_hora=falsas, tasa_deteccion_global=tasa,
    )


def _umbral_calibrado(
    delta_t: np.ndarray, meta: pd.DataFrame, hz: float, pasos: int, falsas_objetivo: float
) -> tuple[float, np.ndarray]:
    """Umbral térmico más sensible cuyo ritmo de falsas alarmas no excede el objetivo."""
    mejor_umbral, mejores_indices = BARRIDO_UMBRALES_K[-1], alarma_umbral(
        delta_t, BARRIDO_UMBRALES_K[-1], PERSISTENCIA_TERMICA
    )
    for umbral in BARRIDO_UMBRALES_K:  # de menor a mayor: el primero que cumple es el más sensible
        indices = alarma_umbral(delta_t, float(umbral), PERSISTENCIA_TERMICA)
        _, falsas, _ = _evaluar_alarmas(indices, meta, hz, pasos)
        if falsas <= falsas_objetivo:
            return float(umbral), indices
    return float(mejor_umbral), mejores_indices


def medir_latencia_streaming(
    detector: DetectorTemporal, senales: np.ndarray, n_pasos: int = 400
) -> tuple[float, float]:
    """Latencia (p50, p95) en ms de una inferencia muestra a muestra en CPU."""
    flujo = detector.streaming()
    latencias = [flujo.paso(senales[k % senales.shape[0]]).latencia_ms for k in range(n_pasos)]
    tiles = np.percentile(latencias[50:], [50, 95])  # se descartan los primeros pasos (arranque)
    return float(tiles[0]), float(tiles[1])


def evaluar_benchmark(
    detector: DetectorTemporal,
    n_secuencias: int = 600,
    semilla: int = 20_000,
    progreso: Callable[[str], None] | None = None,
) -> InformeBenchmark:
    """Ejecuta el benchmark completo sobre secuencias nuevas (semilla de prueba aislada).

    Args:
        detector: detector entrenado.
        n_secuencias: tamaño del conjunto de prueba.
        semilla: debe diferir de las de entrenamiento/validación (0 y 10 000 por defecto).
        progreso: callback opcional de mensajes.
    """
    senales, _, meta = generar_secuencias(n_secuencias, semilla=semilla)
    hz, pasos = FRECUENCIA_HZ, senales.shape[1]

    probs = detector.probabilidades(senales)
    p_evento = probs[..., Clase.LLAMA_FRIA] + probs[..., Clase.LLAMA_CALIENTE]
    idx_ignis = primera_alarma(p_evento >= UMBRAL_ALARMA, MUESTRAS_PERSISTENCIA)
    res_ignis = _resultado(
        "IGNIS · TCN multicanal",
        f"Red temporal causal sobre 6 canales; alarma con {MUESTRAS_PERSISTENCIA} votos seguidos.",
        idx_ignis, meta, hz, pasos,
    )

    delta_t = senales[..., 0]
    idx_fijo = alarma_umbral(delta_t, UMBRAL_TERMICO_FIJO_K, PERSISTENCIA_TERMICA)
    res_fijo = _resultado(
        f"Umbral térmico fijo ({UMBRAL_TERMICO_FIJO_K:.0f} K)",
        "Detector clásico de un canal con persistencia de 5 muestras.",
        idx_fijo, meta, hz, pasos,
    )

    umbral_cal, idx_cal = _umbral_calibrado(
        delta_t, meta, hz, pasos, falsas_objetivo=res_ignis.falsas_alarmas_por_hora
    )
    res_cal = _resultado(
        f"Umbral térmico calibrado ({umbral_cal:.0f} K)",
        "Mismo detector, con el umbral más sensible que no supera las falsas alarmas de IGNIS.",
        idx_cal, meta, hz, pasos,
    )

    idx_luz = alarma_umbral(senales[..., 2], UMBRAL_LUZ_VISIBLE, PERSISTENCIA_LUZ)
    res_luz = _resultado(
        "Cámara visible",
        "Lo que ve un astronauta o una cámara convencional: solo llamas luminosas.",
        idx_luz, meta, hz, pasos,
    )

    p50, p95 = medir_latencia_streaming(detector, senales[0])
    if progreso:
        progreso("benchmark completo")
    return InformeBenchmark(
        n_secuencias=n_secuencias,
        duracion_s=pasos / hz,
        frecuencia_hz=hz,
        metodos=[res_ignis, res_fijo, res_cal, res_luz],
        latencia_inferencia_ms_p50=p50,
        latencia_inferencia_ms_p95=p95,
    )
