"""Pipeline de datos: ingesta de CSV externos (PSI), versionado con hash y perfilado.

Flujo: CSV crudo --(mapeo de columnas y unidades)--> esquema IGNIS --(validación)-->
snapshot inmutable en data/versiones/<fecha>_<hash>/ + copia en data/processed/.
Cada versión guarda su manifiesto (origen, hash, perfil, mapeo): trazabilidad completa,
porque un modelo "entrenado con datos NASA" debe poder demostrar con cuáles.

Uso (CLI):
    python -m src.pipeline_datos sintetico --n 6000
    python -m src.pipeline_datos ingestar --csv data/raw/psi.csv --mapeo data/raw/mapeo_psi.json --origen real
    python -m src.pipeline_datos versiones
    python -m src.pipeline_datos perfil --id 20261012-101500_ab12cd34
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.config import obtener_configuracion
from src.data_loader import (
    COLUMNA_EXPERIMENTO,
    COLUMNA_MATERIAL,
    COLUMNA_OBJETIVO,
    COLUMNA_REGIMEN,
    COLUMNAS_ENTRADA,
    ErrorDatos,
    validar_dataframe,
)
from src.dataset_sintetico import RANGOS_VELOCIDAD_MAX_MM_S, generar_dataset_sintetico
from src.domain import RANGOS, Material, RegimenFlujo
from src.preprocessing import construir_objetivos

logger = logging.getLogger(__name__)

PATRON_ID_VERSION = re.compile(r"^\d{8}-\d{6}_[0-9a-f]{8}$")
UMBRAL_COBERTURA_CATEGORIA = 0.10   # por debajo, la categoría está poco representada
UMBRAL_COBERTURA_RANGO = 0.02       # fracción mínima de datos por quinto del rango
N_TRAMOS_COBERTURA = 5
UMBRAL_COBERTURA_DOMINIO = 0.5      # fracción mínima del dominio operativo que debe cubrir cada variable

# Conversión a la unidad canónica de cada columna: valor_canónico = valor·factor + desplazamiento
UNIDADES: dict[str, dict[str, tuple[float, float]]] = {
    "fraccion_o2": {"fraccion": (1.0, 0.0), "porcentaje": (0.01, 0.0)},
    "velocidad_flujo_cm_s": {
        "cm_s": (1.0, 0.0), "m_s": (100.0, 0.0), "mm_s": (0.1, 0.0), "in_s": (2.54, 0.0),
        "ft_s": (30.48, 0.0),
    },
    "presion_kpa": {
        "kpa": (1.0, 0.0), "pa": (0.001, 0.0), "psi": (6.894757, 0.0), "atm": (101.325, 0.0),
        "bar": (100.0, 0.0), "mbar": (0.1, 0.0), "torr": (0.133322, 0.0),
    },
    "temperatura_ambiente_k": {
        "k": (1.0, 0.0), "c": (1.0, 273.15), "f": (5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
    },
    "espesor_combustible_mm": {
        "mm": (1.0, 0.0), "cm": (10.0, 0.0), "m": (1000.0, 0.0), "in": (25.4, 0.0), "mil": (0.0254, 0.0),
        "um": (0.001, 0.0),
    },
    "velocidad_propagacion_mm_s": {
        "mm_s": (1.0, 0.0), "cm_s": (10.0, 0.0), "m_s": (1000.0, 0.0), "in_s": (25.4, 0.0),
        "ft_s": (304.8, 0.0),
    },
}


class MapeoColumna(BaseModel):
    """De dónde sale una columna canónica en el CSV externo."""

    columna: str = Field(..., description="Nombre de la columna en el CSV de origen.")
    unidad: str = Field(..., description="Unidad de origen (ver UNIDADES).")


class MapeoCSV(BaseModel):
    """Descripción JSON de cómo traducir un CSV de PSI al esquema de IGNIS."""

    columnas: dict[str, MapeoColumna]
    material: str | None = Field(default=None, description="Columna del material.")
    material_alias: dict[str, str] = Field(default_factory=dict)
    regimen: str | None = Field(default=None, description="Columna del régimen de flujo.")
    regimen_alias: dict[str, str] = Field(default_factory=dict)
    id_experimento: str | None = Field(default=None, description="Columna que identifica el experimento.")
    material_fijo: str | None = Field(default=None, description="Si todo el CSV es de un material.")
    constantes: dict[str, float] = Field(
        default_factory=dict,
        description="Variables constantes en todo el archivo, YA en unidad canónica (p. ej. presion_kpa: 101.3).",
    )
    regimen_fijo: str | None = None


class PerfilColumna(BaseModel):
    """Estadísticos de una columna numérica."""

    minimo: float
    maximo: float
    media: float
    desviacion: float


class PerfilDataset(BaseModel):
    """Ficha del dataset (data card) con diagnóstico de cobertura."""

    n_filas: int
    columnas: dict[str, PerfilColumna]
    fraccion_propaga: float
    por_material: dict[str, int]
    por_regimen: dict[str, int]
    n_experimentos: int | None
    huecos_de_cobertura: list[str]


class VersionDataset(BaseModel):
    """Manifiesto de un snapshot de dataset."""

    id: str
    creado_utc: str
    origen: Literal["real", "sintetico"]
    n_filas: int
    sha256: str
    archivo: str
    perfil: PerfilDataset
    mapeo: dict | None = None
    notas: str = ""


# --- Perfilado ---------------------------------------------------------------
def perfilar_dataset(datos: pd.DataFrame) -> PerfilDataset:
    """Calcula la ficha del dataset y señala dónde faltan datos.

    Los huecos son una guía de adquisición: dicen qué experimentos de PSI
    conviene priorizar para que el modelo deje de extrapolar.
    """
    columnas = {
        c: PerfilColumna(
            minimo=float(datos[c].min()), maximo=float(datos[c].max()),
            media=float(datos[c].mean()), desviacion=float(datos[c].std(ddof=0)),
        )
        for c in (*COLUMNAS_ENTRADA, COLUMNA_OBJETIVO)
    }
    _, propaga = construir_objetivos(datos)
    por_material = {str(k): int(v) for k, v in datos[COLUMNA_MATERIAL].value_counts().items()}
    regimen = datos[COLUMNA_REGIMEN] if COLUMNA_REGIMEN in datos.columns else pd.Series(dtype=str)
    por_regimen = {str(k): int(v) for k, v in regimen.value_counts().items()}

    huecos: list[str] = []
    n = len(datos)
    # Se recorren TODAS las categorías esperadas: una categoría ausente (0 filas) es el hueco más grave
    esperadas = (
        ("material", por_material, [m.value for m in Material]),
        ("régimen de flujo", por_regimen, [r.value for r in RegimenFlujo]),
    )
    for etiqueta, conteos, categorias in esperadas:
        for nombre in categorias:
            cuenta = conteos.get(nombre, 0)
            if cuenta / n < UMBRAL_COBERTURA_CATEGORIA:
                huecos.append(f"Poca cobertura de {etiqueta} '{nombre}': {100 * cuenta / n:.1f} % de las filas")
    for variable in COLUMNAS_ENTRADA:
        minimo, maximo = RANGOS[variable]
        bordes = np.linspace(datos[variable].min(), datos[variable].max(), N_TRAMOS_COBERTURA + 1)
        if bordes[-1] <= bordes[0]:
            huecos.append(f"'{variable}' es constante: el modelo no puede aprender su efecto")
            continue
        cuentas, _ = np.histogram(datos[variable], bins=bordes)
        for i, cuenta in enumerate(cuentas):
            if cuenta / n < UMBRAL_COBERTURA_RANGO:
                huecos.append(
                    f"Hueco en '{variable}' ∈ [{bordes[i]:.3g}, {bordes[i + 1]:.3g}]: {100 * cuenta / n:.1f} % de las filas"
                )
        # El dominio operativo es mayor que lo observado: el resto es extrapolación
        cobertura = (datos[variable].max() - datos[variable].min()) / (maximo - minimo)
        if cobertura < UMBRAL_COBERTURA_DOMINIO:
            huecos.append(
                f"'{variable}' observada en [{datos[variable].min():.3g}, {datos[variable].max():.3g}]: cubre solo "
                f"{100 * cobertura:.0f} % del dominio operativo [{minimo:g}, {maximo:g}]"
            )
    return PerfilDataset(
        n_filas=n, columnas=columnas, fraccion_propaga=float(propaga.mean()),
        por_material=por_material, por_regimen=por_regimen,
        n_experimentos=int(datos[COLUMNA_EXPERIMENTO].nunique()) if COLUMNA_EXPERIMENTO in datos.columns else None,
        huecos_de_cobertura=huecos,
    )


# --- Mapeo PSI → esquema IGNIS ---------------------------------------------------
def _construir_destino(crudo: pd.DataFrame, mapeo: MapeoCSV) -> pd.DataFrame:
    """Aplica columnas + unidades + alias SIN validar rangos (la validación la hace quien llama).

    Raises:
        ErrorDatos: si falta una columna mapeada o la unidad no existe para esa variable.
    """
    destino = pd.DataFrame(index=crudo.index)
    obligatorias = (*COLUMNAS_ENTRADA, COLUMNA_OBJETIVO)
    for canonica in obligatorias:
        if canonica in mapeo.constantes and canonica not in mapeo.columnas:
            destino[canonica] = float(mapeo.constantes[canonica])
            continue
        if canonica not in mapeo.columnas:
            raise ErrorDatos(f"El mapeo no define la columna '{canonica}'")
        origen = mapeo.columnas[canonica]
        if origen.columna not in crudo.columns:
            raise ErrorDatos(f"El CSV no tiene la columna '{origen.columna}' (para '{canonica}')")
        unidades = UNIDADES[canonica]
        clave = origen.unidad.strip().lower()
        if clave not in unidades:
            raise ErrorDatos(f"Unidad '{origen.unidad}' no válida para '{canonica}'; usar: {sorted(unidades)}")
        factor, desplazamiento = unidades[clave]
        numerica = pd.to_numeric(crudo[origen.columna], errors="coerce")
        destino[canonica] = numerica * factor + desplazamiento

    destino[COLUMNA_MATERIAL] = _columna_categorica(
        crudo, mapeo.material, mapeo.material_alias, mapeo.material_fijo, COLUMNA_MATERIAL
    )
    if mapeo.regimen or mapeo.regimen_fijo:
        destino[COLUMNA_REGIMEN] = _columna_categorica(
            crudo, mapeo.regimen, mapeo.regimen_alias, mapeo.regimen_fijo, COLUMNA_REGIMEN
        )
    if mapeo.id_experimento:
        if mapeo.id_experimento not in crudo.columns:
            raise ErrorDatos(f"El CSV no tiene la columna de experimento '{mapeo.id_experimento}'")
        destino[COLUMNA_EXPERIMENTO] = crudo[mapeo.id_experimento].astype(str)
    return destino


def normalizar_con_mapeo(crudo: pd.DataFrame, mapeo: MapeoCSV) -> pd.DataFrame:
    """Aplica el mapeo (columnas + unidades + alias) y devuelve el esquema IGNIS validado.

    Estricto: cualquier fila inválida aborta (para CSV curados a mano).

    Raises:
        ErrorDatos: si falta una columna mapeada, la unidad no existe para esa variable
            o el resultado no valida.
    """
    return validar_dataframe(_construir_destino(crudo, mapeo))


def filtrar_filas_validas(destino: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Descarta las filas inválidas y cuenta por qué (para datos crudos de PSI).

    A diferencia de `validar_dataframe`, no aborta: un archivo real tiene huecos y filas fuera del
    dominio operativo, y lo útil es saber cuántas se pierden y por qué. Una fila puede sumar a
    varios motivos; `filas_descartadas` cuenta cada fila una sola vez.

    Returns:
        (filas válidas ya validadas, motivos → nº de filas).
    """
    motivos: dict[str, int] = {}
    invalida = pd.Series(False, index=destino.index)

    def anotar(mascara: pd.Series, texto: str) -> None:
        nonlocal invalida
        if mascara.any():
            motivos[texto] = int(mascara.sum())
            invalida = invalida | mascara

    for columna in (*COLUMNAS_ENTRADA, COLUMNA_OBJETIVO):
        numerica = pd.to_numeric(destino[columna], errors="coerce")
        destino = destino.assign(**{columna: numerica})
        anotar(numerica.isna(), f"{columna}: sin valor numérico")
    for columna in COLUMNAS_ENTRADA:
        minimo, maximo = RANGOS[columna]
        anotar(destino[columna].notna() & ~destino[columna].between(minimo, maximo),
               f"{columna}: fuera del dominio operativo [{minimo:g}, {maximo:g}]")
    anotar(destino[COLUMNA_OBJETIVO].notna() & ~destino[COLUMNA_OBJETIVO].between(0.0, RANGOS_VELOCIDAD_MAX_MM_S),
           f"{COLUMNA_OBJETIVO}: fuera de [0, {RANGOS_VELOCIDAD_MAX_MM_S:g}]")
    material = destino[COLUMNA_MATERIAL].astype(str).str.strip().str.lower()
    anotar(~material.isin({m.value for m in Material}), "material desconocido")
    if COLUMNA_REGIMEN in destino.columns:
        regimen = destino[COLUMNA_REGIMEN].astype(str).str.strip().str.lower()
        anotar(~regimen.isin({r.value for r in RegimenFlujo}), "régimen de flujo desconocido")
    validas = destino.loc[~invalida]
    if validas.empty:
        return validas, {**motivos, "filas_descartadas": int(invalida.sum())}
    motivos["filas_descartadas"] = int(invalida.sum())
    return validar_dataframe(validas), motivos


def normalizar_filas_con_mapeo(crudo: pd.DataFrame, mapeo: MapeoCSV) -> tuple[pd.DataFrame, dict[str, int]]:
    """Variante tolerante: mapea y descarta filas inválidas contando los motivos.

    Raises:
        ErrorDatos: si falta una columna mapeada o la unidad no existe (error de mapeo, no de datos).
    """
    return filtrar_filas_validas(_construir_destino(crudo, mapeo))


def _columna_categorica(
    crudo: pd.DataFrame, columna: str | None, alias: dict[str, str], fijo: str | None, nombre: str
) -> pd.Series:
    """Columna categórica desde el CSV (con alias) o con un valor fijo para todo el archivo."""
    if columna is not None:
        if columna not in crudo.columns:
            raise ErrorDatos(f"El CSV no tiene la columna '{columna}' (para '{nombre}')")
        minusculas = {k.strip().lower(): v for k, v in alias.items()}
        limpia = crudo[columna].astype(str).str.strip().str.lower()
        return limpia.map(lambda v: minusculas.get(v, v))
    if fijo is not None:
        return pd.Series(fijo.strip().lower(), index=crudo.index)
    raise ErrorDatos(f"El mapeo no define '{nombre}' (columna o valor fijo)")


# --- Versionado ---------------------------------------------------------------
def _hash_dataframe(datos: pd.DataFrame) -> str:
    """SHA-256 del contenido canónico (independiente del orden de columnas y del formato)."""
    columnas = sorted(datos.columns)
    bytes_csv = datos[columnas].to_csv(index=False, float_format="%.10g").encode("utf-8")
    return hashlib.sha256(bytes_csv).hexdigest()


def _directorio_versiones(directorio_datos: Path) -> Path:
    return directorio_datos / "versiones"


def registrar_version(
    datos: pd.DataFrame,
    directorio_datos: Path,
    origen: Literal["real", "sintetico"],
    mapeo: MapeoCSV | None = None,
    notas: str = "",
) -> VersionDataset:
    """Guarda un snapshot inmutable del dataset y su manifiesto; actualiza `processed/`.

    Si ya existe una versión con el mismo contenido (hash), se reutiliza: ingestar
    dos veces el mismo archivo no duplica ni ensucia el historial.
    """
    validado = validar_dataframe(datos)
    sha = _hash_dataframe(validado)
    existente = next((v for v in listar_versiones(directorio_datos) if v.sha256 == sha), None)
    if existente is not None:
        logger.info("Dataset ya versionado", extra={"id": existente.id})
        return existente

    ahora = datetime.now(timezone.utc)
    identificador = f"{ahora:%Y%m%d-%H%M%S}_{sha[:8]}"
    carpeta = _directorio_versiones(directorio_datos) / identificador
    carpeta.mkdir(parents=True, exist_ok=False)
    archivo = carpeta / "datos.csv"
    validado.to_csv(archivo, index=False)
    version = VersionDataset(
        id=identificador, creado_utc=ahora.isoformat(), origen=origen, n_filas=len(validado),
        sha256=sha, archivo=str(archivo.relative_to(directorio_datos)),
        perfil=perfilar_dataset(validado),
        mapeo=mapeo.model_dump() if mapeo else None, notas=notas,
    )
    (carpeta / "manifiesto.json").write_text(version.model_dump_json(indent=2), encoding="utf-8")

    procesado = directorio_datos / "processed"
    procesado.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archivo, procesado / f"dataset_{origen}_actual.csv")
    logger.info("Versión de dataset registrada", extra={"id": identificador, "filas": len(validado)})
    return version


def listar_versiones(directorio_datos: Path) -> list[VersionDataset]:
    """Versiones existentes, la más reciente primero. Manifiestos ilegibles se omiten con aviso."""
    raiz = _directorio_versiones(directorio_datos)
    if not raiz.is_dir():
        return []
    versiones: list[VersionDataset] = []
    for manifiesto in sorted(raiz.glob("*/manifiesto.json"), reverse=True):
        try:
            versiones.append(VersionDataset.model_validate_json(manifiesto.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            logger.warning("Manifiesto ilegible; se omite", extra={"ruta": str(manifiesto)}, exc_info=True)
    return versiones


def obtener_version(directorio_datos: Path, identificador: str) -> VersionDataset:
    """Manifiesto de una versión concreta.

    Raises:
        ErrorDatos: si el identificador es inválido (anti path traversal) o no existe.
    """
    if not PATRON_ID_VERSION.fullmatch(identificador):
        raise ErrorDatos(f"Identificador de versión inválido: {identificador!r}")
    ruta = _directorio_versiones(directorio_datos) / identificador / "manifiesto.json"
    if not ruta.is_file():
        raise ErrorDatos(f"No existe la versión {identificador}")
    return VersionDataset.model_validate_json(ruta.read_text(encoding="utf-8"))


def cargar_version(directorio_datos: Path, identificador: str) -> pd.DataFrame:
    """Carga el DataFrame de una versión, verificando que su hash no cambió.

    Raises:
        ErrorDatos: si la versión no existe o el archivo fue alterado.
    """
    version = obtener_version(directorio_datos, identificador)
    datos = validar_dataframe(pd.read_csv(directorio_datos / version.archivo))
    if _hash_dataframe(datos) != version.sha256:
        raise ErrorDatos(f"La versión {identificador} fue modificada (el hash no coincide)")
    return datos


def ingestar_csv(
    ruta_csv: Path,
    directorio_datos: Path,
    origen: Literal["real", "sintetico"],
    ruta_mapeo: Path | None = None,
    notas: str = "",
) -> VersionDataset:
    """Ingesta un CSV externo (con mapeo opcional) y lo versiona.

    Raises:
        ErrorDatos: si el archivo o el mapeo no existen o no son válidos.
    """
    if not ruta_csv.is_file():
        raise ErrorDatos(f"No existe el CSV: {ruta_csv}")
    try:
        crudo = pd.read_csv(ruta_csv)
    except (pd.errors.ParserError, UnicodeDecodeError, pd.errors.EmptyDataError) as error:
        raise ErrorDatos(f"CSV ilegible ({ruta_csv.name}): {error}") from error
    mapeo: MapeoCSV | None = None
    if ruta_mapeo is not None:
        try:
            mapeo = MapeoCSV.model_validate_json(ruta_mapeo.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ErrorDatos(f"Mapeo inválido ({ruta_mapeo.name}): {error}") from error
        datos = normalizar_con_mapeo(crudo, mapeo)
    else:
        datos = validar_dataframe(crudo)
    return registrar_version(datos, directorio_datos, origen, mapeo, notas)


def generar_y_versionar_sintetico(directorio_datos: Path, n_muestras: int, semilla: int) -> VersionDataset:
    """Genera el dataset sintético y lo registra como versión (origen 'sintetico')."""
    datos = generar_dataset_sintetico(n_muestras, semilla)
    return registrar_version(
        datos, directorio_datos, "sintetico",
        notas=f"Sintético semi-empírico (n={n_muestras}, semilla={semilla}); NO son datos NASA.",
    )


# --- CLI -----------------------------------------------------------------------
def _escribir_json(objeto: BaseModel | list[BaseModel]) -> None:
    carga = [o.model_dump() for o in objeto] if isinstance(objeto, list) else objeto.model_dump()
    sys.stdout.write(json.dumps(carga, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada de la CLI; devuelve el código de salida."""
    analizador = argparse.ArgumentParser(prog="pipeline_datos", description=__doc__.split("\n")[0])
    sub = analizador.add_subparsers(dest="orden", required=True)
    p_sint = sub.add_parser("sintetico", help="Genera y versiona el dataset sintético")
    p_sint.add_argument("--n", type=int, default=6000)
    p_sint.add_argument("--semilla", type=int, default=42)
    p_ing = sub.add_parser("ingestar", help="Ingesta un CSV (opcionalmente con mapeo PSI)")
    p_ing.add_argument("--csv", type=Path, required=True)
    p_ing.add_argument("--mapeo", type=Path)
    p_ing.add_argument("--origen", choices=["real", "sintetico"], required=True)
    p_ing.add_argument("--notas", default="")
    p_psi = sub.add_parser("psi", help="Ingesta data/raw/psi/<experimento>/ y reporta la cobertura")
    p_psi.add_argument("--raiz", type=Path, help="Por defecto <datos>/raw/psi")
    p_psi.add_argument("--notas", default="")
    sub.add_parser("versiones", help="Lista las versiones")
    p_per = sub.add_parser("perfil", help="Muestra el perfil de una versión")
    p_per.add_argument("--id", required=True)
    args = analizador.parse_args(argv)

    config = obtener_configuracion()
    try:
        if args.orden == "sintetico":
            _escribir_json(generar_y_versionar_sintetico(config.directorio_datos, args.n, args.semilla))
        elif args.orden == "ingestar":
            _escribir_json(
                ingestar_csv(args.csv, config.directorio_datos, args.origen, args.mapeo, args.notas)
            )
        elif args.orden == "psi":
            from src.ingesta_psi import ingestar_psi  # import tardío: ingesta_psi importa este módulo

            resultado = ingestar_psi(args.raiz or config.directorio_datos / "raw" / "psi", config.directorio_datos, args.notas)
            _escribir_json(resultado.reporte)
            if resultado.version is None:
                sys.stderr.write("AVISO: no se registró ninguna versión (sin filas válidas de propagación)\n")
                return 3
        elif args.orden == "versiones":
            _escribir_json(listar_versiones(config.directorio_datos))
        else:
            _escribir_json(obtener_version(config.directorio_datos, args.id).perfil)
    except ErrorDatos as error:
        logger.error("Error de datos", extra={"detalle": str(error)})
        sys.stderr.write(f"ERROR: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
