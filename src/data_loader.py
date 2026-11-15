"""Carga y validación de datos de entrenamiento (CSV real o sintético)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pandas as pd

from src.dataset_sintetico import RANGOS_VELOCIDAD_MAX_MM_S, generar_dataset_sintetico
from src.domain import RANGOS, Material, RegimenFlujo

logger = logging.getLogger(__name__)

COLUMNAS_ENTRADA: tuple[str, ...] = (
    "fraccion_o2",
    "velocidad_flujo_cm_s",
    "presion_kpa",
    "temperatura_ambiente_k",
    "espesor_combustible_mm",
)
COLUMNA_MATERIAL = "material"
COLUMNA_REGIMEN = "regimen_flujo"  # opcional en CSV: por defecto "opuesto"
COLUMNA_EXPERIMENTO = "id_experimento"  # opcional: evita fuga entre train/test
COLUMNA_OBJETIVO = "velocidad_propagacion_mm_s"
COLUMNAS_REQUERIDAS: tuple[str, ...] = (*COLUMNAS_ENTRADA, COLUMNA_MATERIAL, COLUMNA_OBJETIVO)


class ErrorDatos(ValueError):
    """Dataset ausente, malformado o con valores físicamente imposibles."""


def validar_dataframe(datos: pd.DataFrame) -> pd.DataFrame:
    """Valida esquema, nulos y rangos físicos; devuelve una copia limpia.

    Falla de forma ruidosa (ErrorDatos): entrenar con datos corruptos produce un
    modelo que parece funcionar y miente en silencio. Las columnas opcionales
    (`regimen_flujo`, `id_experimento`) se conservan; `regimen_flujo` se rellena
    con "opuesto" si falta, para aceptar CSV antiguos.

    Raises:
        ErrorDatos: si falta una columna, hay nulos, categorías desconocidas o
            valores fuera de rango.
    """
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in datos.columns]
    if faltantes:
        raise ErrorDatos(f"Columnas faltantes: {faltantes}")
    if datos.empty:
        raise ErrorDatos("El dataset está vacío")

    opcionales = [c for c in (COLUMNA_REGIMEN, COLUMNA_EXPERIMENTO) if c in datos.columns]
    limpio = datos.loc[:, [*COLUMNAS_REQUERIDAS, *opcionales]].copy()
    if limpio[list(COLUMNAS_REQUERIDAS)].isna().any().any():
        columnas_nulas = limpio.columns[limpio.isna().any()].tolist()
        raise ErrorDatos(f"Valores nulos en columnas: {columnas_nulas}")

    for columna in (*COLUMNAS_ENTRADA, COLUMNA_OBJETIVO):
        limpio[columna] = pd.to_numeric(limpio[columna], errors="coerce")
        if limpio[columna].isna().any():
            raise ErrorDatos(f"Valores no numéricos en '{columna}'")

    for columna in COLUMNAS_ENTRADA:
        minimo, maximo = RANGOS[columna]
        fuera = ~limpio[columna].between(minimo, maximo)
        if fuera.any():
            raise ErrorDatos(
                f"{int(fuera.sum())} valores de '{columna}' fuera de [{minimo}, {maximo}]"
            )
    if not limpio[COLUMNA_OBJETIVO].between(0.0, RANGOS_VELOCIDAD_MAX_MM_S).all():
        raise ErrorDatos(f"'{COLUMNA_OBJETIVO}' fuera de [0, {RANGOS_VELOCIDAD_MAX_MM_S}]")

    limpio[COLUMNA_MATERIAL] = limpio[COLUMNA_MATERIAL].astype(str).str.strip().str.lower()
    desconocidos = set(limpio[COLUMNA_MATERIAL]) - {m.value for m in Material}
    if desconocidos:
        raise ErrorDatos(f"Materiales desconocidos: {sorted(desconocidos)}")

    if COLUMNA_REGIMEN in limpio.columns:
        limpio[COLUMNA_REGIMEN] = limpio[COLUMNA_REGIMEN].astype(str).str.strip().str.lower()
        desconocidos = set(limpio[COLUMNA_REGIMEN]) - {r.value for r in RegimenFlujo}
        if desconocidos:
            raise ErrorDatos(f"Regímenes de flujo desconocidos: {sorted(desconocidos)}")
    else:
        limpio[COLUMNA_REGIMEN] = RegimenFlujo.OPUESTO.value
    return limpio.reset_index(drop=True)


def cargar_csv(ruta: Path) -> pd.DataFrame:
    """Lee y valida un CSV con el esquema documentado en data/README.md.

    Raises:
        ErrorDatos: si el archivo no existe, no se puede parsear o no valida.
    """
    if not ruta.is_file():
        raise ErrorDatos(f"No existe el archivo de datos: {ruta}")
    try:
        crudo = pd.read_csv(ruta)
    except (pd.errors.ParserError, UnicodeDecodeError, pd.errors.EmptyDataError) as error:
        logger.error("CSV ilegible", extra={"ruta": str(ruta)}, exc_info=True)
        raise ErrorDatos(f"CSV ilegible ({ruta.name}): {error}") from error
    datos = validar_dataframe(crudo)
    logger.info("CSV cargado", extra={"ruta": str(ruta), "filas": len(datos)})
    return datos


async def cargar_csv_async(ruta: Path) -> pd.DataFrame:
    """Versión async: delega el I/O bloqueante a un hilo para no frenar el event loop."""
    return await asyncio.to_thread(cargar_csv, ruta)


def cargar_dataset(
    ruta_csv: Path | None, n_muestras_sinteticas: int, semilla: int
) -> tuple[pd.DataFrame, str]:
    """Devuelve `(datos, origen)` con origen 'real' o 'sintetico'.

    Si `ruta_csv` está configurada y falla, se propaga el error: degradar en
    silencio a datos sintéticos haría pasar un modelo de juguete por uno real.
    """
    if ruta_csv is not None:
        return cargar_csv(ruta_csv), "real"
    logger.warning(
        "Sin dataset real configurado: usando dataset sintético semi-empírico",
        extra={"n_muestras": n_muestras_sinteticas},
    )
    return validar_dataframe(generar_dataset_sintetico(n_muestras_sinteticas, semilla)), "sintetico"
