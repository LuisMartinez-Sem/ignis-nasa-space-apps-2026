"""Dataset sintético semi-empírico: andamio cualitativo hasta cargar datos PSI reales.

Codifica tendencias reportadas para propagación de llama sobre sólidos delgados
en microgravedad: la velocidad crece con O2, alcanza un máximo a flujo intermedio
y cae a flujo bajo (extinción radiativa) y alto (soplado). Las constantes son de
ESCALA ILUSTRATIVA salvo en las ANCLAS: la ley se calibra para reproducir Saffire-I (1.8 mm/s
concurrente, 1.3 mm/s opuesto; `data/anclas_reales.json`) y se inyectan filas ancla. Las demás
condiciones siguen siendo extrapolación semi-empírica (ver docs/science.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.domain import RANGOS, Material, RegimenFlujo

# --- Constantes de la ley semi-empírica (escala ilustrativa) -----------------
# Calibrado con Saffire-I (opuesto, 21.7 % O2, 20 cm/s, 0.4 mm → 1.3 mm/s). Valor previo ilustrativo: 8.0
VELOCIDAD_REFERENCIA_MM_S = 3.7905  # SIBAL, aire, flujo pico, 0.1 mm
FLUJO_PICO_CM_S = 10.0            # flujo con velocidad de propagación máxima
FRACCION_O2_AIRE = 0.21
LIMITE_O2_MINIMO = 0.16           # LOI mínimo (en el flujo pico) a presión de referencia
CURVATURA_LIMITE_O2 = 0.025       # cuánto sube el LOI al alejarse del flujo pico (por ln²)
PRESION_REFERENCIA_KPA = 101.325
ESPESOR_REFERENCIA_MM = 0.1
ESPESOR_ESCALA_MM = 0.3
RUIDO_RELATIVO = 0.08             # ruido multiplicativo (lognormal)
# Anclas Saffire-I (≈1.8 vs ≈1.3 mm/s): confianza MEDIA, cifras de una presentación de Ferkul (no verificadas en NTRS).
TEMPERATURA_REFERENCIA_K = 295.0
EXPONENTE_TEMPERATURA = 1.5       # el precalentamiento del gas acelera la propagación
FACTOR_CONCURRENTE = 1.2802       # calibrado: reproduce 1.8 mm/s concurrente (Saffire-I) con la razón 1.8/1.3
DESPLAZAMIENTO_LIMITE_CONCURRENTE = -0.01  # sostener la llama concurrente es más fácil
FRACCION_CONCURRENTE_MUESTRAS = 0.35
TEMPERATURA_REFERENCIA_K = 295.0  # un gas ambiente más caliente precalienta el combustible

# Tope físico razonable para validar datos (mm/s); compartido con el cargador
RANGOS_VELOCIDAD_MAX_MM_S = 200.0

RUTA_ANCLAS = Path(__file__).resolve().parent.parent / "data" / "anclas_reales.json"
FILAS_POR_ANCLA = 40              # filas ancla por cada ancla de entrenamiento
MUESTRAS_MINIMAS_PARA_ANCLAS = 500  # con menos filas no se inyectan (pruebas pequeñas)
JITTER_ANCLA = 0.015              # ±1.5 % en O2, flujo y presión alrededor de la condición publicada
RUIDO_ANCLA = 0.05                # incertidumbre relativa de la cifra publicada


def cargar_anclas(ruta: Path = RUTA_ANCLAS) -> list[dict]:
    """Lee las anclas publicadas (`data/anclas_reales.json`).

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el JSON está roto o no tiene la clave `anclas`.
    """
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON de anclas inválido: {error}") from error
    if not isinstance(datos.get("anclas"), list):
        raise ValueError("El archivo de anclas no tiene la lista 'anclas'")
    return datos["anclas"]


def anclas_de_velocidad(ruta: Path = RUTA_ANCLAS) -> list[dict]:
    """Anclas de velocidad con `uso=entrenamiento` (las que entran al generador)."""
    return [a for a in cargar_anclas(ruta)
            if a.get("uso") == "entrenamiento" and a.get("magnitud") == "velocidad_propagacion_mm_s"]

FACTOR_MATERIAL: dict[Material, float] = {
    Material.SIBAL: 1.0,
    Material.PMMA: 0.6,
    Material.CELULOSA: 1.2,
}
DESPLAZAMIENTO_LIMITE_O2: dict[Material, float] = {
    Material.SIBAL: 0.0,
    Material.PMMA: 0.03,
    Material.CELULOSA: -0.01,
}


def limite_o2_extincion(
    velocidad_flujo_cm_s: np.ndarray,
    presion_kpa: np.ndarray,
    desplazamiento: np.ndarray,
) -> np.ndarray:
    """Fracción de O2 mínima para sostener la llama (mínimo en el flujo pico).

    Sube a flujo bajo (pérdidas radiativas) y alto (soplado), y a baja presión.
    El `clip` del flujo evita ln(0) sin cambiar el comportamiento físico relevante.
    """
    flujo = np.clip(velocidad_flujo_cm_s, 0.5, None)
    termino_flujo = CURVATURA_LIMITE_O2 * np.log(flujo / FLUJO_PICO_CM_S) ** 2
    termino_presion = (PRESION_REFERENCIA_KPA / presion_kpa) ** 0.5
    return (LIMITE_O2_MINIMO + termino_flujo) * termino_presion + desplazamiento


def velocidad_propagacion_ideal_mm_s(
    fraccion_o2: np.ndarray,
    velocidad_flujo_cm_s: np.ndarray,
    presion_kpa: np.ndarray,
    espesor_combustible_mm: np.ndarray,
    factor_material: np.ndarray,
    limite_o2: np.ndarray,
    factor_regimen: np.ndarray | float = 1.0,
    temperatura_ambiente_k: np.ndarray | float = TEMPERATURA_REFERENCIA_K,
) -> np.ndarray:
    """Velocidad de propagación sin ruido (mm/s); 0 bajo el límite de extinción."""
    razon_flujo = velocidad_flujo_cm_s / FLUJO_PICO_CM_S
    # Máximo exacto (=1) en el flujo pico; 0 sin flujo
    efecto_flujo = razon_flujo * np.exp(1.0 - razon_flujo)
    efecto_o2 = (fraccion_o2 / FRACCION_O2_AIRE) ** 1.5
    efecto_presion = (presion_kpa / PRESION_REFERENCIA_KPA) ** 0.3
    efecto_temperatura = (temperatura_ambiente_k / TEMPERATURA_REFERENCIA_K) ** EXPONENTE_TEMPERATURA
    efecto_espesor = (1 + ESPESOR_REFERENCIA_MM / ESPESOR_ESCALA_MM) / (
        1 + espesor_combustible_mm / ESPESOR_ESCALA_MM
    )
    # Transición suave hacia el límite: cerca de la extinción la llama es muy lenta
    exceso_o2 = np.clip(fraccion_o2 - limite_o2, 0.0, None)
    atenuacion_limite = 1.0 - np.exp(-exceso_o2 / 0.03)
    return (
        VELOCIDAD_REFERENCIA_MM_S * factor_material * factor_regimen * efecto_flujo
        * efecto_o2 * efecto_presion * efecto_espesor * efecto_temperatura * atenuacion_limite
    )


def generar_dataset_sintetico(n_muestras: int, semilla: int = 42) -> pd.DataFrame:
    """Genera `n_muestras` filas con el esquema del CSV real (ver data/README.md).

    Args:
        n_muestras: número de filas (>0).
        semilla: semilla del generador para reproducibilidad.

    Returns:
        DataFrame con columnas de entrada y `velocidad_propagacion_mm_s`.
    """
    if n_muestras <= 0:
        raise ValueError("n_muestras debe ser positivo")
    rng = np.random.default_rng(semilla)

    fraccion_o2 = rng.uniform(*RANGOS["fraccion_o2"], n_muestras)
    # Log-uniforme: la física cambia más en flujos bajos que en altos
    velocidad_flujo = np.exp(rng.uniform(np.log(0.5), np.log(60.0), n_muestras))
    presion = rng.uniform(*RANGOS["presion_kpa"], n_muestras)
    temperatura = rng.uniform(285.0, 320.0, n_muestras)
    espesor = np.exp(rng.uniform(np.log(0.05), np.log(3.0), n_muestras))
    # Se elige por índice: rng.choice sobre un Enum lo degrada a numpy.str_
    catalogo = list(Material)
    materiales = [catalogo[i] for i in rng.integers(0, len(catalogo), n_muestras)]
    es_concurrente = rng.random(n_muestras) < FRACCION_CONCURRENTE_MUESTRAS

    factor = np.array([FACTOR_MATERIAL[m] for m in materiales])
    desplazamiento = np.array([DESPLAZAMIENTO_LIMITE_O2[m] for m in materiales])
    desplazamiento = desplazamiento + np.where(es_concurrente, DESPLAZAMIENTO_LIMITE_CONCURRENTE, 0.0)
    factor_regimen = np.where(es_concurrente, FACTOR_CONCURRENTE, 1.0)
    limite = limite_o2_extincion(velocidad_flujo, presion, desplazamiento)
    ideal = velocidad_propagacion_ideal_mm_s(
        fraccion_o2, velocidad_flujo, presion, espesor, factor, limite, factor_regimen, temperatura
    )
    velocidad = ideal * rng.lognormal(0.0, RUIDO_RELATIVO, n_muestras)

    datos = pd.DataFrame(
        {
            "fraccion_o2": fraccion_o2,
            "velocidad_flujo_cm_s": velocidad_flujo,
            "presion_kpa": presion,
            "temperatura_ambiente_k": temperatura,
            "espesor_combustible_mm": espesor,
            "material": [m.value for m in materiales],
            "regimen_flujo": np.where(
                es_concurrente, RegimenFlujo.CONCURRENTE.value, RegimenFlujo.OPUESTO.value
            ),
            "velocidad_propagacion_mm_s": np.clip(velocidad, 0.0, RANGOS_VELOCIDAD_MAX_MM_S),
        }
    )
    if n_muestras >= MUESTRAS_MINIMAS_PARA_ANCLAS:
        datos = _inyectar_anclas(datos, rng)
    return datos


def _inyectar_anclas(datos: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Sustituye las últimas filas por filas ancla (condiciones publicadas ± jitter, valor publicado ± ruido).

    El total de filas no cambia. Cada ancla aporta `FILAS_POR_ANCLA` filas.
    """
    anclas = anclas_de_velocidad()
    filas = []
    for ancla in anclas:
        c = ancla["condiciones"]
        for _ in range(FILAS_POR_ANCLA):
            salto = 1.0 + rng.uniform(-JITTER_ANCLA, JITTER_ANCLA, 3)
            filas.append({
                "fraccion_o2": float(np.clip(c["fraccion_o2"] * salto[0], *RANGOS["fraccion_o2"])),
                "velocidad_flujo_cm_s": float(c["velocidad_flujo_cm_s"] * salto[1]),
                "presion_kpa": float(np.clip(c["presion_kpa"] * salto[2], *RANGOS["presion_kpa"])),
                "temperatura_ambiente_k": float(c["temperatura_ambiente_k"]),
                "espesor_combustible_mm": float(c["espesor_combustible_mm"]),
                "material": c["material"],
                "regimen_flujo": c["regimen_flujo"],
                "velocidad_propagacion_mm_s": float(ancla["valor"] * rng.lognormal(0.0, RUIDO_ANCLA)),
            })
    if not filas or len(filas) >= len(datos):
        return datos
    anclas_df = pd.DataFrame(filas)[list(datos.columns)]
    return pd.concat([datos.iloc[: len(datos) - len(anclas_df)], anclas_df], ignore_index=True)
