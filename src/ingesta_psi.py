"""Ingesta de datos PSI: leer → inferir unidades → normalizar → cobertura por experimento → versionar.

Orquesta `lector_psi` (formatos y unidades) y `pipeline_datos` (conversión, filtrado y versionado
con SHA-256). Entrada: `data/raw/psi/<experimento>/*.{csv,tsv,txt,json,h5,hdf5}`; opcional
`data/raw/psi/<experimento>/mapeo.json` (formato `MapeoCSV`) que manda sobre la inferencia.

Solo los experimentos de rol `propagacion` entran al dataset de entrenamiento. Los de rol
`llama_fria` (FLEX, CFI) se leen y se reportan, pero NO se mezclan con la propagación sobre sólidos.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from src.data_loader import COLUMNA_EXPERIMENTO, ErrorDatos
from src.lector_psi import (
    CATALOGO_PSI, ExperimentoPsi, RolExperimento, descubrir_archivos, inferir_mapeo, leer_tabla,
)
from src.pipeline_datos import (
    MapeoCSV, VersionDataset, normalizar_filas_con_mapeo, registrar_version,
)

logger = logging.getLogger(__name__)

NOMBRE_COBERTURA = "cobertura_psi.json"
FILAS_MINIMAS_RECOMENDADAS = 30  # por debajo, el reentrenamiento con datos reales no es fiable


class CoberturaExperimento(BaseModel):
    """Qué se pudo leer de un experimento y qué se perdió."""

    experimento: str
    nombre: str
    rol: RolExperimento
    estado: str  # ok | parcial | omitido
    archivos_leidos: list[str] = Field(default_factory=list)
    archivos_omitidos: dict[str, str] = Field(default_factory=dict)  # archivo → motivo
    formatos: list[str] = Field(default_factory=list)
    filas_crudas: int = 0
    filas_validas: int = 0
    descartadas: dict[str, int] = Field(default_factory=dict)
    variables_mapeadas: dict[str, str] = Field(default_factory=dict)  # canónica → "columna [unidad]"
    supuestos: list[str] = Field(default_factory=list)
    rangos_observados: dict[str, tuple[float, float]] = Field(default_factory=dict)
    entra_al_entrenamiento: bool = False


class ReporteCoberturaPsi(BaseModel):
    """Cobertura por experimento + totales verificables (de aquí salen las cifras del pitch)."""

    generado_utc: str
    raiz: str
    experimentos: list[CoberturaExperimento]
    filas_entrenamiento: int
    filas_por_experimento: dict[str, int]
    avisos: list[str] = Field(default_factory=list)


class ResultadoIngestaPsi(BaseModel):
    """Versión registrada (None si no hubo ninguna fila válida) y su reporte."""

    version: VersionDataset | None
    reporte: ReporteCoberturaPsi


def _cargar_mapeo_manual(carpeta: Path) -> MapeoCSV | None:
    """`mapeo.json` del experimento, si existe.

    Raises:
        ErrorDatos: si existe pero es inválido (se prefiere fallar a ignorarlo en silencio).
    """
    ruta = carpeta / "mapeo.json"
    if not ruta.is_file():
        return None
    try:
        return MapeoCSV.model_validate_json(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ErrorDatos(f"Mapeo inválido ({ruta}): {error}") from error


def _procesar_experimento(
    clave: str, rutas: list[tuple[Path, str]], carpeta: Path
) -> tuple[CoberturaExperimento, pd.DataFrame | None]:
    """Lee todos los archivos de un experimento y devuelve su cobertura y sus filas válidas."""
    ficha: ExperimentoPsi | None = CATALOGO_PSI.get(clave)
    cobertura = CoberturaExperimento(
        experimento=clave, nombre=ficha.nombre if ficha else "(fuera del catálogo)",
        rol=ficha.rol if ficha else RolExperimento.PROPAGACION, estado="omitido",
    )
    if ficha is None:
        cobertura.supuestos.append(
            f"'{clave}' no está en el catálogo de PSI conocido; se trata como propagación sobre sólidos"
        )
    mapeo_manual = _cargar_mapeo_manual(carpeta)
    partes: list[pd.DataFrame] = []
    for ruta, _formato in rutas:
        try:
            tabla = leer_tabla(ruta)
            if mapeo_manual is not None:
                mapeo = mapeo_manual
            else:
                inferencia = inferir_mapeo(tabla, ficha)
                cobertura.supuestos.extend(s for s in inferencia.supuestos if s not in cobertura.supuestos)
                sin_cubrir = [v for v in inferencia.faltantes if v not in inferencia.mapeo.get("constantes", {})]
                if sin_cubrir:
                    raise ErrorDatos(
                        f"no se pudieron determinar columnas/unidades de {sin_cubrir}; "
                        f"crea {carpeta.name}/mapeo.json (ver docs/psi_integracion.md)"
                    )
                mapeo = MapeoCSV.model_validate(inferencia.mapeo)
            validas, motivos = normalizar_filas_con_mapeo(tabla.datos, mapeo)
        except (ErrorDatos, ValueError) as error:
            cobertura.archivos_omitidos[ruta.name] = str(error)
            logger.warning("Archivo PSI omitido", extra={"experimento": clave, "archivo": ruta.name, "motivo": str(error)})
            continue
        cobertura.archivos_leidos.append(ruta.name)
        if tabla.formato not in cobertura.formatos:
            cobertura.formatos.append(tabla.formato)
        cobertura.filas_crudas += len(tabla.datos)
        descartadas = motivos.pop("filas_descartadas", 0)
        for motivo, n in motivos.items():
            cobertura.descartadas[motivo] = cobertura.descartadas.get(motivo, 0) + n
        if descartadas:
            cobertura.descartadas["filas_descartadas"] = cobertura.descartadas.get("filas_descartadas", 0) + descartadas
        for canonica, origen in mapeo.columnas.items():
            cobertura.variables_mapeadas.setdefault(canonica, f"{origen.columna} [{origen.unidad}]")
        for canonica, valor in mapeo.constantes.items():
            cobertura.variables_mapeadas.setdefault(canonica, f"constante {valor:g}")
        if validas.empty:
            continue
        if COLUMNA_EXPERIMENTO in validas.columns:
            validas[COLUMNA_EXPERIMENTO] = clave + "/" + validas[COLUMNA_EXPERIMENTO].astype(str)
        else:
            validas[COLUMNA_EXPERIMENTO] = f"{clave}/{ruta.stem}"
        partes.append(validas)

    if not partes:
        return cobertura, None
    datos = pd.concat(partes, ignore_index=True)
    cobertura.filas_validas = len(datos)
    cobertura.estado = "ok" if not cobertura.archivos_omitidos else "parcial"
    cobertura.rangos_observados = {
        c: (float(datos[c].min()), float(datos[c].max()))
        for c in datos.columns if pd.api.types.is_numeric_dtype(datos[c])
    }
    cobertura.entra_al_entrenamiento = cobertura.rol is RolExperimento.PROPAGACION
    return cobertura, datos


def ingestar_psi(raiz_psi: Path, directorio_datos: Path, notas: str = "") -> ResultadoIngestaPsi:
    """Ingesta todo `raiz_psi`, genera el reporte de cobertura y versiona el dataset unificado.

    Args:
        raiz_psi: carpeta `data/raw/psi` con una subcarpeta por experimento.
        directorio_datos: carpeta `data/` (donde viven `versiones/` y `processed/`).
        notas: texto libre para el manifiesto de la versión.

    Returns:
        Versión registrada (None si no hay filas válidas de propagación) y reporte de cobertura.

    Raises:
        ErrorDatos: si un `mapeo.json` es inválido.
    """
    archivos, avisos = descubrir_archivos(raiz_psi)
    por_experimento: dict[str, list[tuple[Path, str]]] = {}
    for archivo in archivos:
        por_experimento.setdefault(archivo.experimento, []).append((archivo.ruta, archivo.formato))

    coberturas: list[CoberturaExperimento] = []
    entrenamiento: list[pd.DataFrame] = []
    for clave in sorted(por_experimento):
        cobertura, datos = _procesar_experimento(clave, por_experimento[clave], raiz_psi / clave)
        coberturas.append(cobertura)
        if datos is not None and cobertura.entra_al_entrenamiento:
            entrenamiento.append(datos)
    if not archivos:
        avisos.append("No hay archivos PSI soportados: descarga datos primero (docs/psi_integracion.md)")

    filas_por_experimento = {c.experimento: c.filas_validas for c in coberturas}
    unificado = pd.concat(entrenamiento, ignore_index=True) if entrenamiento else None
    n_total = 0 if unificado is None else len(unificado)
    if 0 < n_total < FILAS_MINIMAS_RECOMENDADAS:
        avisos.append(f"Solo {n_total} filas válidas (< {FILAS_MINIMAS_RECOMENDADAS}): el reentrenamiento no es fiable")
    for c in coberturas:
        if c.rol is RolExperimento.LLAMA_FRIA and c.filas_validas:
            avisos.append(f"{c.experimento}: {c.filas_validas} filas de llama fría NO se usan para entrenar la propagación")
    reporte = ReporteCoberturaPsi(
        generado_utc=datetime.now(timezone.utc).isoformat(), raiz=str(raiz_psi), experimentos=coberturas,
        filas_entrenamiento=n_total,
        filas_por_experimento=filas_por_experimento, avisos=avisos,
    )

    version: VersionDataset | None = None
    if unificado is not None:
        resumen = ", ".join(f"{k}={v}" for k, v in filas_por_experimento.items() if v)
        version = registrar_version(
            unificado, directorio_datos, "real",
            notas=(notas + " " if notas else "") + f"PSI unificado ({resumen}).",
        )
        destino = directorio_datos / Path(version.archivo).parent / NOMBRE_COBERTURA
        destino.write_text(reporte.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Ingesta PSI terminada", extra={"filas": n_total, "experimentos": len(coberturas)})
    return ResultadoIngestaPsi(version=version, reporte=reporte)


def cargar_cobertura(directorio_datos: Path, version: VersionDataset) -> ReporteCoberturaPsi | None:
    """Reporte de cobertura guardado junto a una versión (None si la versión no viene de PSI)."""
    ruta = directorio_datos / Path(version.archivo).parent / NOMBRE_COBERTURA
    if not ruta.is_file():
        return None
    try:
        return ReporteCoberturaPsi.model_validate(json.loads(ruta.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        logger.warning("Cobertura PSI ilegible", extra={"ruta": str(ruta)}, exc_info=True)
        return None
