"""Cool Flames: llamas de baja temperatura, invisibles, sin emisión visible.

MODELO HEURÍSTICO (v0). Las Cool Flames (observadas en FLEX con gotas de alcanos)
ocurren en una ventana de temperatura de reacción ~550–800 K y pueden persistir
tras la extinción de la llama caliente. La forma gaussiana y los centros son
hipótesis de trabajo a calibrar con FLEX/BASS; ver docs/science.md.
"""

from __future__ import annotations

import numpy as np

from src.domain import EstadoLlamaFria

# --- Hipótesis de la ventana de Cool Flame (calibrar con datos reales) -------
# Ancla FLEX (Nayagam): ventana 550–800 K. Con centro 675 K y ancho 150 K, 550 y 800 K son el semimáximo.
TEMPERATURA_CENTRO_K = 675.0
TEMPERATURA_ANCHO_K = 150.0
FRACCION_O2_CENTRO = 0.18
FRACCION_O2_ANCHO = 0.09
PRESION_MEDIA_KPA = 50.0       # a menor presión, la química de baja T se debilita
PRESION_ESCALA_KPA = 20.0

UMBRAL_POSIBLE = 0.25
UMBRAL_PROBABLE = 0.60


def probabilidad_llama_fria(
    temperatura_reaccion_k: np.ndarray,
    fraccion_o2: np.ndarray,
    presion_kpa: np.ndarray,
) -> np.ndarray:
    """Probabilidad [0,1] de Cool Flame; NaN donde no hay lectura de temperatura.

    Producto de tres factores suaves (temperatura, O2, presión): basta que uno sea
    incompatible para anular la probabilidad, como en una ventana de ignición real.
    """
    temperatura = np.asarray(temperatura_reaccion_k, dtype=float)
    o2 = np.asarray(fraccion_o2, dtype=float)
    presion = np.asarray(presion_kpa, dtype=float)

    factor_temperatura = np.exp(-(((temperatura - TEMPERATURA_CENTRO_K) / TEMPERATURA_ANCHO_K) ** 2))
    factor_o2 = np.exp(-(((o2 - FRACCION_O2_CENTRO) / FRACCION_O2_ANCHO) ** 2))
    factor_presion = 1.0 / (1.0 + np.exp(-(presion - PRESION_MEDIA_KPA) / PRESION_ESCALA_KPA))
    probabilidad = factor_temperatura * factor_o2 * factor_presion
    # NaN en la entrada se propaga solo: distingue "no medido" de "probabilidad 0"
    return np.clip(probabilidad, 0.0, 1.0)


def clasificar_estado(probabilidad: float | None) -> EstadoLlamaFria:
    """Traduce probabilidad a estado discreto; `None`/NaN => NO_EVALUADA."""
    if probabilidad is None or np.isnan(probabilidad):
        return EstadoLlamaFria.NO_EVALUADA
    if probabilidad >= UMBRAL_PROBABLE:
        return EstadoLlamaFria.PROBABLE
    if probabilidad >= UMBRAL_POSIBLE:
        return EstadoLlamaFria.POSIBLE
    return EstadoLlamaFria.INACTIVA
