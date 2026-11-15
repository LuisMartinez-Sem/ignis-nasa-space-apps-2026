"""Métricas y mediciones compartidas por todos los motores (comparación justa)."""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
from pydantic import BaseModel
from sklearn.metrics import accuracy_score, brier_score_loss, mean_absolute_error, r2_score, roc_auc_score

N_BINS_CALIBRACION = 10


class MetricasEntrenamiento(BaseModel):
    """Métricas sobre el conjunto de prueba reservado; auditables desde la API."""

    r2_velocidad: float
    mae_velocidad_mm_s: float
    exactitud_propagacion: float
    auc_propagacion: float
    brier_propagacion: float
    ece_propagacion: float
    n_entrenamiento: int
    n_prueba: int


class PerfilLatencia(BaseModel):
    """Latencia de inferencia por lote y por muestra, en milisegundos."""

    p50_ms: float
    p95_ms: float
    por_muestra_us: float
    n_repeticiones: int
    tamano_lote: int


def error_calibracion_esperado(
    verdad: np.ndarray, probabilidad: np.ndarray, n_bins: int = N_BINS_CALIBRACION
) -> float:
    """ECE: diferencia media (ponderada) entre confianza y frecuencia real por intervalo.

    Importa más que la exactitud: un 90 % de probabilidad debe cumplirse el 90 % de
    las veces para que el operador pueda confiar en el número.
    """
    bordes = np.linspace(0.0, 1.0, n_bins + 1)
    # digitize con bordes internos => índices 0..n_bins-1; 1.0 cae en el último
    cajas = np.clip(np.digitize(probabilidad, bordes[1:-1]), 0, n_bins - 1)
    ece = 0.0
    for caja in range(n_bins):
        mascara = cajas == caja
        if mascara.any():
            ece += mascara.mean() * abs(verdad[mascara].mean() - probabilidad[mascara].mean())
    return float(ece)


def calcular_metricas(
    velocidad_real: np.ndarray,
    velocidad_pred: np.ndarray,
    propaga_real: np.ndarray,
    probabilidad_pred: np.ndarray,
    n_entrenamiento: int,
) -> MetricasEntrenamiento:
    """Calcula el conjunto estándar de métricas de IGNIS sobre la partición de prueba."""
    return MetricasEntrenamiento(
        r2_velocidad=float(r2_score(velocidad_real, velocidad_pred)),
        mae_velocidad_mm_s=float(mean_absolute_error(velocidad_real, velocidad_pred)),
        exactitud_propagacion=float(accuracy_score(propaga_real, probabilidad_pred >= 0.5)),
        auc_propagacion=float(roc_auc_score(propaga_real, probabilidad_pred)),
        brier_propagacion=float(brier_score_loss(propaga_real, probabilidad_pred)),
        ece_propagacion=error_calibracion_esperado(propaga_real, probabilidad_pred),
        n_entrenamiento=n_entrenamiento,
        n_prueba=len(velocidad_real),
    )


def medir_latencia(
    funcion: Callable[[], object], n_repeticiones: int = 30, tamano_lote: int = 1, calentamiento: int = 3
) -> PerfilLatencia:
    """Mide el tiempo de pared de `funcion` (una inferencia de `tamano_lote` filas).

    El calentamiento descarta la primera llamada (carga perezosa, cachés), que
    de otro modo dominaría el p95 y daría una imagen falsa del régimen estable.
    """
    for _ in range(calentamiento):
        funcion()
    tiempos_ms = np.empty(n_repeticiones)
    for i in range(n_repeticiones):
        inicio = time.perf_counter()
        funcion()
        tiempos_ms[i] = (time.perf_counter() - inicio) * 1000.0
    return PerfilLatencia(
        p50_ms=float(np.percentile(tiempos_ms, 50)),
        p95_ms=float(np.percentile(tiempos_ms, 95)),
        por_muestra_us=float(tiempos_ms.mean() * 1000.0 / tamano_lote),
        n_repeticiones=n_repeticiones,
        tamano_lote=tamano_lote,
    )
