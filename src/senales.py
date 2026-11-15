"""Generador de series temporales de sensores (SINTÉTICAS) para el detector de llamas.

No hay series reales de llama fría en formato abierto utilizable, así que se simulan
fenómenos cualitativos documentados: una llama fría eleva la temperatura (~600–800 K
absolutos, decenas–centenas de K sobre el ambiente), produce CO y casi NO emite luz
visible; una llama caliente es brillante y mucho más caliente. Se añaden *distractores*
(picos de un solo sensor, calentamiento benigno de equipos) porque un detector que
solo ve "algo caliente" produce falsas alarmas, como la de la ISS en 2015.

Las amplitudes son ilustrativas. Sustituir por series de FLEX/BASS cuando existan.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np
import pandas as pd

# Canales = residuos respecto a la línea base calibrada (como en un sistema real).
CANALES: tuple[str, ...] = (
    "delta_t_k",       # K sobre el ambiente (termopar cercano al combustible)
    "ir_rel",          # radiancia IR relativa (0–1)
    "luz_visible",     # brillo en cámara/fotodiodo visible (0–1)
    "delta_o2_pct",    # variación de O2 (puntos porcentuales; consumo => negativo)
    "delta_p_kpa",     # variación de presión (kPa)
    "co_ppm",          # monóxido de carbono (ppm)
)
N_CANALES = len(CANALES)
# Escala de normalización fija (documentada): mantiene el streaming sin estado extra
ESCALAS: np.ndarray = np.array([200.0, 0.2, 0.3, 0.5, 0.2, 100.0], dtype=np.float32)

FRECUENCIA_HZ = 10.0
DURACION_S = 30.0


class Clase(IntEnum):
    """Clases por muestra."""

    NOMINAL = 0
    LLAMA_FRIA = 1
    LLAMA_CALIENTE = 2


TIPOS_EVENTO: tuple[str, ...] = (
    "nominal", "artefacto", "calentamiento", "fria", "fria_a_caliente", "caliente",
)
# Probabilidades de cada tipo; la mitad de las secuencias contienen fuego real
PROBABILIDADES_TIPO: tuple[float, ...] = (0.18, 0.14, 0.12, 0.22, 0.14, 0.20)
TIPOS_NEGATIVOS = frozenset({"nominal", "artefacto", "calentamiento"})


def normalizar(senales: np.ndarray) -> np.ndarray:
    """Escala los canales a magnitudes ~O(1) (dividir por `ESCALAS`)."""
    return (senales / ESCALAS).astype(np.float32)


def _subida(t: np.ndarray, t0: np.ndarray, tau: np.ndarray) -> np.ndarray:
    """Respuesta de primer orden que arranca en t0: 0 antes, 1-exp(-(t-t0)/tau) después."""
    transcurrido = np.clip(t - t0, 0.0, None)
    return 1.0 - np.exp(-transcurrido / tau)


def generar_secuencias(
    n_secuencias: int,
    semilla: int = 0,
    duracion_s: float = DURACION_S,
    frecuencia_hz: float = FRECUENCIA_HZ,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Genera secuencias etiquetadas por muestra (vectorizado).

    Returns:
        senales: (n, T, C) float32 en unidades físicas.
        etiquetas: (n, T) int64 con `Clase`.
        meta: DataFrame con `tipo`, `t_inicio_s`, `t_caliente_s` (NaN si no aplica).

    Raises:
        ValueError: si los parámetros no son positivos.
    """
    if n_secuencias <= 0 or duracion_s <= 0 or frecuencia_hz <= 0:
        raise ValueError("n_secuencias, duracion_s y frecuencia_hz deben ser positivos")
    rng = np.random.default_rng(semilla)
    n = n_secuencias
    pasos = int(round(duracion_s * frecuencia_hz))
    t = (np.arange(pasos) / frecuencia_hz)[None, :]  # (1, T)

    tipo_idx = rng.choice(len(TIPOS_EVENTO), size=n, p=PROBABILIDADES_TIPO)
    tipo = np.array(TIPOS_EVENTO)[tipo_idx]
    col = lambda *a: rng.uniform(*a, size=(n, 1))  # noqa: E731  (parámetro por secuencia)

    t0 = col(3.0, duracion_s * 0.6)
    tau_frio = col(1.0, 3.5)
    tau_caliente = col(0.3, 1.2)
    t_transicion = t0 + col(4.0, 10.0)  # solo usado en fria_a_caliente

    es_frio = np.isin(tipo, ("fria", "fria_a_caliente"))[:, None]
    es_caliente = (tipo == "caliente")[:, None]
    es_trans = (tipo == "fria_a_caliente")[:, None]
    es_calentamiento = (tipo == "calentamiento")[:, None]

    # --- Fenómenos físicos (cada término vale 0 si el tipo no aplica) ----------
    amp_frio = col(25.0, 220.0)
    amp_caliente = col(350.0, 1200.0)
    sube_frio = _subida(t, t0, tau_frio) * es_frio
    # En la transición la etapa fría se completa y la caliente toma el relevo
    sube_caliente = (
        _subida(t, t0, tau_caliente) * es_caliente
        + _subida(t, t_transicion, tau_caliente) * es_trans
    )
    delta_t = amp_frio * sube_frio + (amp_caliente - amp_frio * es_trans) * sube_caliente
    # Calentamiento benigno: rampa lenta y pequeña, sin CO ni luz
    rampa = np.clip((t - t0) / col(15.0, 40.0), 0.0, 1.0)
    delta_t = delta_t + col(15.0, 60.0) * rampa * es_calentamiento

    activo = sube_frio + sube_caliente  # 0..~2: intensidad de reacción química
    transcurrido_reaccion = np.clip(t - t0, 0.0, None) * np.clip(activo, 0, 1)
    co = col(0.8, 15.0) * transcurrido_reaccion * (1.0 + 2.0 * sube_caliente)
    # Desgasificación de equipos que se calientan: algo de CO también sin fuego (solapamiento real)
    co = co + col(0.3, 2.0) * np.clip(t - t0, 0.0, None) * es_calentamiento * (rng.random((n, 1)) < 0.4)
    luz = col(0.5, 1.0) * _subida(t, np.where(es_trans, t_transicion, t0), col(0.1, 0.3)) * (
        es_caliente | es_trans
    )
    ir = np.clip(delta_t, 0, None) ** 1.5 / (1200.0 ** 1.5) * col(0.8, 1.2)
    delta_o2 = -col(0.002, 0.02) * transcurrido_reaccion * np.clip(activo, 0, 1)
    delta_p = col(0.01, 0.1) * np.clip(activo, 0, 2)

    # --- Ruido, deriva y distractores ----------------------------------------
    deriva = np.cumsum(rng.normal(0, 0.03, (n, pasos)), axis=1)
    senales = np.stack(
        [
            delta_t + deriva + rng.normal(0, 1, (n, 1)) * rng.uniform(0.3, 1.2, (n, pasos)),
            ir + rng.normal(0, 0.003, (n, pasos)),
            luz + rng.normal(0, 0.004, (n, pasos)),
            delta_o2 + rng.normal(0, 0.003, (n, pasos)),
            delta_p + rng.normal(0, 0.01, (n, pasos)),
            co + rng.normal(0, 1.5, (n, pasos)),
        ],
        axis=-1,
    )
    # Picos de un solo sensor (1–3 muestras): 100 % de los "artefacto" y 25 % del resto
    con_picos = (tipo == "artefacto") | (rng.random(n) < 0.25)
    amplitudes = np.array([300.0, 0.6, 0.8, 1.0, 1.5, 150.0])  # tamaño típico por canal
    for indice in np.flatnonzero(con_picos):
        for _ in range(rng.integers(1, 4)):
            canal = rng.integers(0, N_CANALES)
            inicio = rng.integers(0, pasos - 3)
            ancho = rng.integers(1, 4)
            signo = -1.0 if canal == 3 else 1.0
            senales[indice, inicio : inicio + ancho, canal] += signo * amplitudes[canal] * rng.uniform(0.4, 1.2)
    senales[..., 1:3] = np.clip(senales[..., 1:3], 0.0, None)  # IR y luz no son negativos
    senales[..., 5] = np.clip(senales[..., 5], 0.0, None)

    # --- Etiquetas: sin evento = 0; fría = 1; caliente = 2 --------------------
    etiquetas = np.zeros((n, pasos), dtype=np.int64)
    inicio_evento = np.broadcast_to(t0, (n, pasos))
    etiquetas = np.where(
        es_frio & (t >= inicio_evento) & ~((t >= t_transicion) & es_trans),
        int(Clase.LLAMA_FRIA),
        etiquetas,
    )
    etiquetas = np.where(
        (es_caliente & (t >= inicio_evento)) | (es_trans & (t >= t_transicion)),
        int(Clase.LLAMA_CALIENTE),
        etiquetas,
    )

    meta = pd.DataFrame(
        {
            "tipo": tipo,
            "t_inicio_s": np.where(np.isin(tipo, ("fria", "fria_a_caliente", "caliente")), t0[:, 0], np.nan),
            "t_caliente_s": np.where(tipo == "fria_a_caliente", t_transicion[:, 0], np.where(tipo == "caliente", t0[:, 0], np.nan)),
        }
    )
    return senales.astype(np.float32), etiquetas, meta
