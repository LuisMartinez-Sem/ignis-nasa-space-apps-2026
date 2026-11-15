"""Importación de un CSV de PRUEBA: permite ensayar cómo entran datos nuevos sin tocar el catálogo ni la ingesta reales.

Los datos van a `data/investigaciones_prueba.json` (misma forma que la ingesta real). El cargador los aplica DESPUÉS de la
ingesta real, así que son reversibles (borrar el archivo) y nunca contaminan `investigaciones.json`. Todo lo que entra por aquí
queda marcado como PRUEBA en `fuente` y en el nombre, para que no pueda confundirse con un dato de la NASA.

Reutiliza el mismo mapeo de columnas y conversión de unidades que `scripts/ingestar_datos_nasa.py`: lo que se ensaya es
exactamente el camino que seguirán los datos reales (nada de atajos distintos).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from src import investigaciones as inv

logger = logging.getLogger(__name__)

NOMBRE_ARCHIVO = "investigaciones_prueba.json"
MAX_CARACTERES = 512_000  # ~500 KB: de sobra para un CSV de ensayo, evita abusos
MAX_FILAS = 5_000
MARCA = "DATOS DE PRUEBA (no son datos de la NASA)"

PLANTILLA_CSV = (
    "Investigation,Fuel,Hardware,O2 (%),Flow (cm/s),Pressure (kPa),Objectives\n"
    "Demo-Luna-A,Papel de celulosa,Glovebox demo,30,10,70,Ensayo: material a atmósfera lunar\n"
    "Demo-Luna-A,Papel de celulosa,Glovebox demo,35,10,60,Ensayo: material a atmósfera lunar\n"
    "Demo-Luna-A,Papel de celulosa,Glovebox demo,40,20,55,Ensayo: material a atmósfera lunar\n"
    "Demo-Marte-B,Tela de algodón,Cámara demo,25,5,52,Ensayo: tela a presión marciana\n"
    "Demo-Marte-B,Tela de algodón,Cámara demo,28,5,48,Ensayo: tela a presión marciana\n"
    "Demo-ISS-C,Polímero,Cámara demo,21,15,101,Ensayo: referencia a atmósfera ISS\n"
)


class InformeImportacion(BaseModel):
    """Resultado de una importación de prueba: qué se entendió, qué se ignoró y por qué."""

    estado: str = Field(description="ok | sin_coincidencias")
    filas: int
    investigaciones_nuevas: list[str]
    investigaciones_actualizadas: list[str]
    columnas_reconocidas: dict[str, str] = Field(description="Columna del archivo → campo del catálogo")
    columnas_ignoradas: list[str]
    omitidas: list[str] = Field(description="Valores omitidos por unidad ambigua (no se adivinan)")
    conflictos: list[str] = Field(description="Valores que contradicen el catálogo (se conserva el catálogo)")
    no_mapeadas: list[str]
    aviso: str = MARCA


class ErrorImportacion(ValueError):
    """CSV inutilizable (vacío, sin columna de identificación, demasiado grande…). El mensaje es apto para mostrarse al usuario."""


def ruta_prueba(ruta_catalogo: Path | None = None) -> Path:
    return (ruta_catalogo or inv.RUTA_CATALOGO).with_name(NOMBRE_ARCHIVO)


def _marcar(ficha: dict) -> dict:
    ficha = dict(ficha)
    ficha["nombre_completo"] = f"{ficha['nombre_completo']} [PRUEBA]"[:140]
    ficha["fuente"] = f"{MARCA}: {ficha['fuente']}"
    return ficha


def importar(contenido: str, ruta_catalogo: Path | None = None) -> InformeImportacion:
    """Procesa el CSV, escribe la superposición de prueba (atómicamente) y devuelve el informe.

    Raises:
        ErrorImportacion: el archivo no se puede usar; no se modifica nada.
    """
    from scripts.ingestar_datos_nasa import leer_tabla, mapear_columnas, procesar_archivo

    if not contenido.strip():
        raise ErrorImportacion("El archivo está vacío.")
    if len(contenido) > MAX_CARACTERES:
        raise ErrorImportacion(f"El archivo supera {MAX_CARACTERES // 1000} KB; para ensayar bastan unas pocas filas.")
    destino = ruta_prueba(ruta_catalogo)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "prueba.csv"
        tmp.write_text(contenido, encoding="utf-8")
        try:
            filas = leer_tabla(tmp)
            if len(filas) > MAX_FILAS:
                raise ErrorImportacion(f"Demasiadas filas ({len(filas)}); el máximo para ensayar es {MAX_FILAS}.")
            mapa = mapear_columnas(list(filas[0].keys()))
            base = inv.cargar_catalogo_sin_prueba(ruta_catalogo)
            r = procesar_archivo(tmp, base)
        except ErrorImportacion:
            raise
        except (ValueError, OSError, UnicodeDecodeError) as error:
            raise ErrorImportacion(str(error)) from error
    nuevas = {k: _marcar(v) for k, v in r["nuevas"].items()}
    actualizaciones = {k: {**v, "fuente_ingesta": f"PRUEBA ({v.get('fuente_ingesta', 'csv')})"} for k, v in r["actualizaciones"].items()}
    if nuevas or actualizaciones:
        destino.parent.mkdir(parents=True, exist_ok=True)
        carga = {"version": "1.1", "prueba": True, "generado": datetime.now(timezone.utc).isoformat(), "actualizaciones": actualizaciones, "nuevas": list(nuevas.values())}
        fd, nombre_tmp = tempfile.mkstemp(dir=destino.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(carga, f, ensure_ascii=False, indent=2)
        os.replace(nombre_tmp, destino)  # atómico: el servidor nunca lee un archivo a medias
    elif destino.exists():
        destino.unlink()
    logger.info("Importación de prueba", extra={"nuevas": len(nuevas), "actualizadas": len(actualizaciones), "filas": len(filas)})
    return InformeImportacion(
        estado="ok" if (nuevas or actualizaciones) else "sin_coincidencias", filas=len(filas),
        investigaciones_nuevas=sorted(nuevas), investigaciones_actualizadas=sorted(actualizaciones), columnas_reconocidas=mapa,
        columnas_ignoradas=r["columnas_ignoradas"], omitidas=r["omitidas"], conflictos=r["conflictos"], no_mapeadas=r["no_mapeadas"])


def quitar(ruta_catalogo: Path | None = None) -> bool:
    """Elimina los datos de prueba. True si había algo que quitar."""
    destino = ruta_prueba(ruta_catalogo)
    if destino.exists():
        destino.unlink()
        return True
    return False
