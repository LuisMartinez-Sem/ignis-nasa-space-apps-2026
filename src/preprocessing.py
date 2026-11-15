"""Ingeniería de características y particiones reproducibles."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from src.data_loader import COLUMNA_EXPERIMENTO, COLUMNA_MATERIAL, COLUMNA_OBJETIVO, COLUMNA_REGIMEN
from src.domain import Material, RegimenFlujo

# Umbral bajo el cual consideramos que la llama se extinguió (ruido de medición)
UMBRAL_PROPAGACION_MM_S = 0.05

COLUMNAS_MATERIAL: tuple[str, ...] = tuple(f"material_{m.value}" for m in Material)
COLUMNAS_CARACTERISTICAS: tuple[str, ...] = (
    "fraccion_o2",
    "log_flujo",
    "presion_kpa",
    "temperatura_ambiente_k",
    "log_espesor",
    "presion_parcial_o2_kpa",
    "regimen_concurrente",
    *COLUMNAS_MATERIAL,
)


def construir_matriz_caracteristicas(datos: pd.DataFrame) -> pd.DataFrame:
    """Construye la matriz de entrada del modelo, vectorizada y con orden fijo.

    - log1p(flujo) y log(espesor): ambos varían en órdenes de magnitud.
    - presión parcial de O2: variable que la física de combustión realmente usa.
    - one-hot con columnas fijas: el orden no depende de qué materiales aparezcan.
    - `regimen_flujo` ausente se asume "opuesto" (compatibilidad con CSV antiguos).

    Raises:
        ValueError: si hay categorías desconocidas o columnas ausentes.
    """
    requeridas = {
        "fraccion_o2", "velocidad_flujo_cm_s", "presion_kpa",
        "temperatura_ambiente_k", "espesor_combustible_mm", COLUMNA_MATERIAL,
    }
    faltantes = requeridas - set(datos.columns)
    if faltantes:
        raise ValueError(f"Columnas faltantes para características: {sorted(faltantes)}")

    materiales = datos[COLUMNA_MATERIAL].astype(str)
    desconocidos = set(materiales) - {m.value for m in Material}
    if desconocidos:
        raise ValueError(f"Materiales desconocidos: {sorted(desconocidos)}")

    if COLUMNA_REGIMEN in datos.columns:
        regimen = datos[COLUMNA_REGIMEN].astype(str)
        desconocidos = set(regimen) - {r.value for r in RegimenFlujo}
        if desconocidos:
            raise ValueError(f"Regímenes de flujo desconocidos: {sorted(desconocidos)}")
        concurrente = (regimen == RegimenFlujo.CONCURRENTE.value).astype(float)
    else:
        concurrente = pd.Series(0.0, index=datos.index)

    matriz = pd.DataFrame(index=datos.index)
    matriz["fraccion_o2"] = datos["fraccion_o2"].astype(float)
    matriz["log_flujo"] = np.log1p(datos["velocidad_flujo_cm_s"].astype(float))
    matriz["presion_kpa"] = datos["presion_kpa"].astype(float)
    matriz["temperatura_ambiente_k"] = datos["temperatura_ambiente_k"].astype(float)
    matriz["log_espesor"] = np.log(datos["espesor_combustible_mm"].astype(float))
    matriz["presion_parcial_o2_kpa"] = matriz["fraccion_o2"] * matriz["presion_kpa"]
    matriz["regimen_concurrente"] = concurrente
    for material in Material:
        matriz[f"material_{material.value}"] = (materiales == material.value).astype(float)
    return matriz[list(COLUMNAS_CARACTERISTICAS)]


def construir_objetivos(datos: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve `(velocidad_mm_s, propaga)` donde `propaga` es 0/1."""
    velocidad = datos[COLUMNA_OBJETIVO].to_numpy(dtype=float)
    propaga = (velocidad > UMBRAL_PROPAGACION_MM_S).astype(int)
    return velocidad, propaga


def dividir_datos(
    datos: pd.DataFrame, semilla: int = 42, fraccion_prueba: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Partición entrenamiento/prueba reproducible, compartida por todos los motores.

    Si existe `id_experimento`, se divide POR EXPERIMENTO: filas del mismo experimento
    son casi idénticas, y mezclarlas entre train y test infla las métricas (fuga).
    Sin grupos, se estratifica por propaga/no propaga.

    Raises:
        ValueError: si el dataset es demasiado pequeño para dividir.
    """
    if len(datos) < 10:
        raise ValueError("Se necesitan al menos 10 filas para dividir el dataset")
    if COLUMNA_EXPERIMENTO in datos.columns and datos[COLUMNA_EXPERIMENTO].nunique() >= 5:
        divisor = GroupShuffleSplit(n_splits=1, test_size=fraccion_prueba, random_state=semilla)
        idx_ent, idx_pru = next(divisor.split(datos, groups=datos[COLUMNA_EXPERIMENTO]))
    else:
        _, propaga = construir_objetivos(datos)
        estratificar = propaga if 0 < propaga.sum() < len(propaga) else None
        idx_ent, idx_pru = train_test_split(
            np.arange(len(datos)), test_size=fraccion_prueba,
            random_state=semilla, stratify=estratificar,
        )
    return datos.iloc[idx_ent].reset_index(drop=True), datos.iloc[idx_pru].reset_index(drop=True)
