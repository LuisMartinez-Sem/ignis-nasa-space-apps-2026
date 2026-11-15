"""Lectura de archivos PSI (CSV/TSV/TXT, JSON, HDF5) e inferencia de columnas y unidades.

Responsabilidad única: convertir un archivo en una tabla + unidades declaradas, y proponer
un mapeo hacia el esquema canónico de IGNIS. NO convierte valores ni versiona (eso es de
`pipeline_datos`); por eso este módulo no importa `pipeline_datos` (evita ciclos).

Honestidad: PSI no publica un formato único. Cuando una columna o su unidad no se pueden
determinar con certeza, se REPORTA y el experimento se omite; nunca se adivina en silencio.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel

from src.data_loader import ErrorDatos

logger = logging.getLogger(__name__)

# Extensión → formato. Todo lo demás (pdf, mp4, zip…) se ignora con aviso.
FORMATOS: dict[str, Literal["csv", "json", "hdf5"]] = {
    ".csv": "csv", ".tsv": "csv", ".txt": "csv", ".json": "json",
    ".h5": "hdf5", ".hdf5": "hdf5", ".hdf": "hdf5",
}
MAX_BYTES_ARCHIVO = 500 * 1024 * 1024  # tope por archivo: evita agotar memoria con descargas enormes
MINIMO_FILAS_HDF5 = 2


class RolExperimento(StrEnum):
    """Qué modelo puede alimentar un experimento."""

    PROPAGACION = "propagacion"  # velocidad de propagación sobre sólidos → entrena RF/profundo
    LLAMA_FRIA = "llama_fria"  # llamas frías (gotas, contraflujo) → calibra cool_flame, NO el modelo de propagación


class ExperimentoPsi(BaseModel):
    """Ficha de un experimento conocido de PSI."""

    clave: str
    nombre: str
    rol: RolExperimento
    material_por_defecto: str | None = None
    nota: str = ""


# Claves = nombre de la carpeta en data/raw/psi/<clave>/. Nombres según la lista oficial de
# investigaciones de PSI (nasa.gov/physical-sciences-informatics-psi/psi-investigations-by-research-area).
CATALOGO_PSI: dict[str, ExperimentoPsi] = {
    e.clave: e for e in (
        ExperimentoPsi(clave="saffire-i", nombre="Spacecraft Fire Experiment-I", rol=RolExperimento.PROPAGACION,
                       material_por_defecto="sibal", nota="Flujo concurrente y opuesto; sólido grande."),
        ExperimentoPsi(clave="saffire-ii", nombre="Spacecraft Fire Experiment-II", rol=RolExperimento.PROPAGACION,
                       material_por_defecto="sibal"),
        ExperimentoPsi(clave="saffire-iii", nombre="Spacecraft Fire Experiment-III", rol=RolExperimento.PROPAGACION,
                       material_por_defecto="sibal"),
        ExperimentoPsi(clave="bass", nombre="Burning and Suppression of Solids", rol=RolExperimento.PROPAGACION,
                       nota="Sólidos en flujo de baja velocidad: el más cercano al modelo de propagación."),
        ExperimentoPsi(clave="bass-ii", nombre="Burning and Suppression of Solids-II", rol=RolExperimento.PROPAGACION),
        ExperimentoPsi(clave="flex", nombre="Flame Extinguishment Experiment", rol=RolExperimento.LLAMA_FRIA,
                       nota="Gotas de combustible y llamas frías: calibra `cool_flame`, no la propagación sobre sólidos."),
        ExperimentoPsi(clave="flex-2", nombre="Flame Extinguishment Experiment-2", rol=RolExperimento.LLAMA_FRIA,
                       nota="Gotas de combustible líquido."),
        ExperimentoPsi(clave="cfi", nombre="Cool Flames Investigation", rol=RolExperimento.LLAMA_FRIA),
    )
}

# --- Variables canónicas: sinónimos de nombre de columna (inglés/español) -------------------
# El ORDEN importa: patrones específicos primero (p. ej. "velocidad de propagación" antes que "velocidad").
_SINONIMOS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (canonica, re.compile(patron, re.IGNORECASE)) for canonica, patron in (
        ("velocidad_propagacion_mm_s", r"(spread|propag|flame.?(speed|rate|velocity)|burn.?rate)"),
        ("velocidad_flujo_cm_s", r"(flow|air.?speed|velocidad.*flujo|flujo|ventilac)"),
        ("fraccion_o2", r"(\bo2\b|o_?2|oxygen|ox[ií]geno)"),
        ("presion_kpa", r"(press|presi[oó]n|^p$|^p_?(kpa|psi|atm|pa|bar)$)"),
        ("espesor_combustible_mm", r"(thick|espesor|grosor)"),
        ("temperatura_ambiente_k", r"(ambient|bulk|chamber|cabin|gas.?temp|t_?amb|ambiente)"),
        ("material", r"(material|fuel|sample|muestra|combustible)"),
        ("regimen", r"(regime|r[eé]gimen|concurrent|opposed|flow.?dir)"),
        ("experimento", r"(experiment|run.?id|test.?id|sample.?id|experimento)"),
    )
)
_COLUMNAS_NUMERICAS = (
    "velocidad_propagacion_mm_s", "velocidad_flujo_cm_s", "fraccion_o2", "presion_kpa",
    "espesor_combustible_mm", "temperatura_ambiente_k",
)

# Alias de unidad (texto normalizado) → clave de `pipeline_datos.UNIDADES`
_ALIAS_UNIDAD: dict[str, str] = {
    "%": "porcentaje", "vol%": "porcentaje", "mol%": "porcentaje", "percent": "porcentaje", "pct": "porcentaje",
    "fraction": "fraccion", "fraccion": "fraccion", "molefraction": "fraccion",
    "kpa": "kpa", "pa": "pa", "psi": "psi", "psia": "psi", "atm": "atm", "bar": "bar", "mbar": "mbar",
    "torr": "torr", "mmhg": "torr",
    "cm/s": "cm_s", "cms-1": "cm_s", "m/s": "m_s", "ms-1": "m_s", "mm/s": "mm_s", "mms-1": "mm_s",
    "in/s": "in_s", "ft/s": "ft_s",
    "k": "k", "kelvin": "k", "c": "c", "°c": "c", "degc": "c", "celsius": "c",
    "f": "f", "°f": "f", "degf": "f", "fahrenheit": "f",
    "mm": "mm", "cm": "cm", "m": "m", "in": "in", "inch": "in", "mil": "mil", "um": "um", "µm": "um", "μm": "um",
}
_PATRON_UNIDAD_NOMBRE = re.compile(r"[\(\[\{]\s*([^\)\]\}]+?)\s*[\)\]\}]\s*$")
_PATRON_UNIDAD_SUFIJO = re.compile(r"_(kpa|psia|psi|pa|atm|bar|mbar|torr|k|c|f|mm|cm|um|in|mil|pct)$", re.IGNORECASE)


class ErrorLecturaPsi(ErrorDatos):
    """Archivo ilegible, demasiado grande o con una estructura no soportada."""


@dataclass
class TablaPsi:
    """Una tabla leída: datos crudos + unidades que el propio archivo declara."""

    datos: pd.DataFrame
    formato: str
    ruta: Path
    unidades_declaradas: dict[str, str] = field(default_factory=dict)


@dataclass
class ArchivoPsi:
    """Archivo descubierto bajo `data/raw/psi/<experimento>/`."""

    ruta: Path
    experimento: str
    formato: str


# ------------------------------------------------------------------ descubrimiento
def descubrir_archivos(raiz: Path) -> tuple[list[ArchivoPsi], list[str]]:
    """Recorre `raiz/<experimento>/**` y clasifica los archivos por formato.

    Args:
        raiz: carpeta `data/raw/psi`.

    Returns:
        (archivos soportados, avisos sobre archivos ignorados).
    """
    archivos: list[ArchivoPsi] = []
    avisos: list[str] = []
    if not raiz.is_dir():
        return archivos, [f"No existe {raiz}"]
    for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir()):
        clave = carpeta.name.strip().lower().replace("_", "-")
        for ruta in sorted(carpeta.rglob("*")):
            if not ruta.is_file() or ruta.name.startswith(".") or ruta.name.lower() == "mapeo.json":
                continue
            formato = FORMATOS.get(ruta.suffix.lower())
            if formato is None:
                avisos.append(f"{clave}: se ignora {ruta.name} (formato '{ruta.suffix}' no soportado)")
                continue
            archivos.append(ArchivoPsi(ruta=ruta, experimento=clave, formato=formato))
    return archivos, avisos


# ------------------------------------------------------------------ lectores
def _comprobar_tamano(ruta: Path) -> None:
    if ruta.stat().st_size > MAX_BYTES_ARCHIVO:
        raise ErrorLecturaPsi(f"{ruta.name} supera {MAX_BYTES_ARCHIVO // (1024 * 1024)} MB; divídelo antes de ingestar")


def _leer_csv(ruta: Path) -> TablaPsi:
    """CSV/TSV/TXT: detecta separador, ignora comentarios '#' y prueba utf-8 y latin-1."""
    ultimo_error: Exception | None = None
    for codificacion in ("utf-8-sig", "latin-1"):
        try:
            datos = pd.read_csv(ruta, sep=None, engine="python", comment="#", encoding=codificacion, skipinitialspace=True)
            return TablaPsi(datos=datos, formato="csv", ruta=ruta)
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
            ultimo_error = error
    raise ErrorLecturaPsi(f"Texto tabular ilegible ({ruta.name}): {ultimo_error}")


def _leer_json(ruta: Path) -> TablaPsi:
    """JSON: lista de registros, {"data"|"rows"|"records": [...]} o dict columnar; unidades opcionales."""
    try:
        bruto = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ErrorLecturaPsi(f"JSON ilegible ({ruta.name}): {error}") from error
    unidades: dict[str, str] = {}
    cuerpo = bruto
    if isinstance(bruto, dict):
        declaradas = bruto.get("units") or bruto.get("unidades")
        if isinstance(declaradas, dict):
            unidades = {str(k): str(v) for k, v in declaradas.items()}
        columnas = bruto.get("columns")
        if isinstance(columnas, list) and all(isinstance(c, dict) and "name" in c for c in columnas):
            unidades.update({str(c["name"]): str(c["unit"]) for c in columnas if c.get("unit")})
        for clave in ("data", "rows", "records"):
            if clave in bruto:
                cuerpo = bruto[clave]
                break
    try:
        if isinstance(cuerpo, list):
            datos = pd.DataFrame(cuerpo)
        elif isinstance(cuerpo, dict):
            datos = pd.DataFrame({k: v for k, v in cuerpo.items() if isinstance(v, list)})
        else:
            raise ValueError("estructura no soportada")
    except (ValueError, TypeError) as error:
        raise ErrorLecturaPsi(f"JSON con estructura no soportada ({ruta.name}): {error}") from error
    if datos.empty:
        raise ErrorLecturaPsi(f"JSON sin filas ({ruta.name})")
    return TablaPsi(datos=datos, formato="json", ruta=ruta, unidades_declaradas=unidades)


def _texto(valor: object) -> str:
    return valor.decode("utf-8", "replace") if isinstance(valor, bytes) else str(valor)


def _leer_hdf5(ruta: Path) -> TablaPsi:
    """HDF5: reúne los datasets 1-D de igual longitud (el grupo más ancho) y lee su atributo 'units'."""
    try:
        import h5py  # noqa: PLC0415  (dependencia opcional: solo si hay archivos HDF5)
    except ImportError as error:
        raise ErrorLecturaPsi("Leer HDF5 requiere h5py: pip install h5py") from error
    candidatos: dict[int, dict[str, tuple[np.ndarray, str]]] = {}
    try:
        with h5py.File(ruta, "r") as archivo:
            def visitar(nombre: str, objeto: object) -> None:
                if isinstance(objeto, h5py.Dataset) and objeto.ndim == 1 and objeto.shape[0] >= MINIMO_FILAS_HDF5:
                    valores = objeto[()]
                    unidad = ""
                    for clave in ("units", "unit", "Units", "UNITS"):
                        if clave in objeto.attrs:
                            unidad = _texto(objeto.attrs[clave])
                            break
                    columna = nombre.split("/")[-1]
                    candidatos.setdefault(int(objeto.shape[0]), {})[columna] = (valores, unidad)
            archivo.visititems(visitar)
    except (OSError, ValueError) as error:
        raise ErrorLecturaPsi(f"HDF5 ilegible ({ruta.name}): {error}") from error
    if not candidatos:
        raise ErrorLecturaPsi(f"HDF5 sin datasets 1-D utilizables ({ruta.name})")
    longitud = max(candidatos, key=lambda n: (len(candidatos[n]), n))  # grupo con más columnas
    columnas = candidatos[longitud]
    datos = pd.DataFrame({
        nombre: [_texto(v) for v in valores] if valores.dtype.kind in "SOU" else valores
        for nombre, (valores, _) in columnas.items()
    })
    unidades = {nombre: unidad for nombre, (_, unidad) in columnas.items() if unidad}
    return TablaPsi(datos=datos, formato="hdf5", ruta=ruta, unidades_declaradas=unidades)


def leer_tabla(ruta: Path) -> TablaPsi:
    """Lee un archivo según su extensión.

    Raises:
        ErrorLecturaPsi: formato no soportado, archivo muy grande o ilegible.
    """
    formato = FORMATOS.get(ruta.suffix.lower())
    if formato is None:
        raise ErrorLecturaPsi(f"Formato no soportado: {ruta.suffix}")
    _comprobar_tamano(ruta)
    tabla = {"csv": _leer_csv, "json": _leer_json, "hdf5": _leer_hdf5}[formato](ruta)
    tabla.datos.columns = [str(c).strip() for c in tabla.datos.columns]
    return tabla


# ------------------------------------------------------------------ inferencia
def normalizar_unidad(texto: str) -> str | None:
    """Texto de unidad libre ('kPa', 'psia', '°C', 'cm/s', '%') → clave canónica, o None si no se reconoce."""
    limpio = re.sub(r"\s+", "", texto.strip().lower()).replace("·", "").replace("^-1", "-1")
    return _ALIAS_UNIDAD.get(limpio)


def _unidad_de_columna(nombre: str, declaradas: dict[str, str]) -> tuple[str | None, str]:
    """Unidad de una columna y de dónde salió ('declarada', 'nombre' o '')."""
    if nombre in declaradas:
        return normalizar_unidad(declaradas[nombre]), "declarada"
    coincidencia = _PATRON_UNIDAD_NOMBRE.search(nombre) or _PATRON_UNIDAD_SUFIJO.search(nombre)
    if coincidencia:
        return normalizar_unidad(coincidencia.group(1)), "nombre"
    return None, ""


def _variable_de_columna(nombre: str) -> str | None:
    sin_unidad = _PATRON_UNIDAD_NOMBRE.sub("", nombre)
    for canonica, patron in _SINONIMOS:
        if patron.search(sin_unidad):
            return canonica
    return None


class InferenciaMapeo(BaseModel):
    """Resultado de analizar las columnas de un archivo."""

    mapeo: dict  # estructura compatible con `pipeline_datos.MapeoCSV` (sin importarlo)
    faltantes: list[str]
    supuestos: list[str]


def inferir_mapeo(tabla: TablaPsi, experimento: ExperimentoPsi | None) -> InferenciaMapeo:
    """Propone el mapeo columnas→esquema IGNIS a partir de nombres, unidades declaradas y magnitudes.

    Reglas: la unidad sale del archivo (atributo/etiqueta/nombre). Solo el O2 se infiere por
    magnitud (≤ 1,5 ⇒ fracción; si no, porcentaje) y queda registrado como supuesto.
    Las demás unidades ausentes se dejan en `faltantes`: hace falta un `mapeo.json`.
    """
    columnas: dict[str, dict[str, str]] = {}
    supuestos: list[str] = []
    extra: dict[str, str] = {}
    for nombre in tabla.datos.columns:
        canonica = _variable_de_columna(nombre)
        if canonica is None:
            continue
        if canonica in _COLUMNAS_NUMERICAS:
            if canonica in columnas:  # primera coincidencia gana; el resto se informa
                supuestos.append(f"Columna '{nombre}' ignorada: '{columnas[canonica]['columna']}' ya cubre {canonica}")
                continue
            unidad, via = _unidad_de_columna(nombre, tabla.unidades_declaradas)
            if unidad is None and canonica == "fraccion_o2":
                valores = pd.to_numeric(tabla.datos[nombre], errors="coerce").dropna()
                if len(valores):
                    unidad = "fraccion" if float(valores.max()) <= 1.5 else "porcentaje"
                    supuestos.append(f"Unidad de '{nombre}' inferida por magnitud (máx {valores.max():.3g}): {unidad}")
            if unidad is not None:
                columnas[canonica] = {"columna": nombre, "unidad": unidad}
        else:
            extra.setdefault(canonica, nombre)

    mapeo: dict = {"columnas": columnas}
    if "material" in extra:
        mapeo["material"] = extra["material"]
    elif experimento and experimento.material_por_defecto:
        mapeo["material_fijo"] = experimento.material_por_defecto
        supuestos.append(f"Material '{experimento.material_por_defecto}' por defecto del experimento {experimento.clave}")
    elif experimento and experimento.rol is RolExperimento.LLAMA_FRIA:
        # Gotas/llama fría: el esquema exige un material, pero no aplica; marcador neutro, fuera del entrenamiento sólido
        mapeo["material_fijo"] = "celulosa"
        supuestos.append("Material 'celulosa' es un MARCADOR: el experimento no usa sólidos y no entra al entrenamiento")
    if "regimen" in extra:
        mapeo["regimen"] = extra["regimen"]
        # PSI suele escribir "concurrent"/"opposed"; se normalizan al vocabulario de IGNIS
        mapeo["regimen_alias"] = {"concurrent": "concurrente", "concurrente": "concurrente",
                                  "opposed": "opuesto", "opposing": "opuesto", "opuesto": "opuesto"}
    else:
        mapeo["regimen_fijo"] = "opuesto"
        supuestos.append("Régimen de flujo no declarado: se asume 'opuesto'")
    if "experimento" in extra:
        mapeo["id_experimento"] = extra["experimento"]
    faltantes = [c for c in _COLUMNAS_NUMERICAS if c not in columnas]
    return InferenciaMapeo(mapeo=mapeo, faltantes=faltantes, supuestos=supuestos)
