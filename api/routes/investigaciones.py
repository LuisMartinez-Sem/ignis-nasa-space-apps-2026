"""SI Dashboard (reto NASA 2026): catálogo, ranking, comparación, huecos y exportación de investigaciones."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, Field

from src import importacion_prueba as prueba
from src import investigaciones as inv
from src.config import obtener_configuracion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/investigaciones", tags=["investigaciones"])
IdInvestigacion = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,39}$", max_length=40)


class ItemCatalogo(BaseModel):
    investigacion: inv.Investigacion
    relevancia: dict[str, float]  # 0-100 por entorno (iss, luna, marte, traje)


class RespuestaCatalogo(BaseModel):
    estado: inv.EstadoCatalogo
    total: int
    aviso: str
    entornos: list[inv.Entorno]
    pesos: dict[str, float]
    items: list[ItemCatalogo]


class RespuestaRanking(BaseModel):
    estado: inv.EstadoCatalogo
    entorno: inv.Entorno
    criterio: str
    total: int
    resultados: list[inv.InvestigacionRankeada]


def _catalogo() -> list[inv.Investigacion]:
    """Catálogo vigente; nunca falla (ante un archivo ausente o corrupto sirve el respaldo hardcodeado)."""
    return inv.cargar_catalogo()


@router.get("", response_model=RespuestaCatalogo)
async def catalogo() -> RespuestaCatalogo:
    """Catálogo con la relevancia (0-100) de cada investigación para ISS, Luna, Marte y traje."""
    lista, estado = inv.cargar_catalogo_con_estado()
    return RespuestaCatalogo(
        estado=estado, total=len(lista),
        aviso="Catálogo construido por IGNIS desde el texto del reto y anclas del equipo; los metadatos reales de PSI no se han leído (campos desconocidos = null).",
        entornos=list(inv.ENTORNOS.values()), pesos=inv.PESOS,
        items=[ItemCatalogo(investigacion=i, relevancia=inv.puntajes_por_entorno(i)) for i in lista])


@router.get("/estado", response_model=inv.EstadoCatalogo)
async def estado_catalogo() -> inv.EstadoCatalogo:
    """Origen del catálogo y su `huella`: si cambia entre dos consultas, hay datos nuevos (el HUD sondea esto cada pocos segundos)."""
    return inv.cargar_catalogo_con_estado()[1]


@router.get("/calidad-datos")
async def calidad_datos() -> dict:
    """Avisos de calidad de las tablas PSI ingestadas (filas vacías, duplicados, erratas, conflictos con el catálogo) para el investigador.

    Lee el reporte de `scripts/ingestar_datos_nasa.py`; si no existe, devuelve una lista vacía (nunca falla)."""
    import json
    ruta = inv.RUTA_CATALOGO.parent / "processed" / "investigaciones_ingestadas_reporte.json"
    try:
        informe = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"generado": None, "archivos": [], "resumen": {"archivos": 0, "atencion": 0, "conflictos": 0, "fallidos": 0}}
    archivos = []
    for a in informe.get("archivos", []):
        cal = a.get("calidad") or {}
        archivos.append({"archivo": a["archivo"], "estado": a["estado"], "motivo": a.get("motivo"), "investigacion": cal.get("investigacion"),
                         "filas_utiles": cal.get("filas_utiles"), "rangos": cal.get("rangos", {}), "avisos": cal.get("avisos", []),
                         "conflictos": a.get("conflictos", [])})
    atencion = sum(1 for a in archivos for x in a["avisos"] if x.get("nivel") == "atencion")
    return {"generado": informe.get("generado"), "archivos": archivos,
            "resumen": {"archivos": len(archivos), "atencion": atencion, "conflictos": sum(len(a["conflictos"]) for a in archivos),
                        "fallidos": sum(1 for a in archivos if a["estado"] == "fallido")}}


class CargaPrueba(BaseModel):
    """CSV de ensayo enviado como texto (el navegador lo lee con FileReader)."""

    contenido: str = Field(min_length=1, max_length=prueba.MAX_CARACTERES)


def _permitir_prueba() -> None:
    """El ensayo escribe en disco: se bloquea en producción (la demo y el desarrollo no lo están)."""
    if obtener_configuracion().entorno == "produccion":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La importación de prueba está desactivada en producción")


@router.get("/prueba/plantilla")
async def plantilla_prueba() -> Response:
    """CSV de ejemplo listo para descargar o cargar: tres investigaciones inventadas (Demo-*) con O₂, flujo y presión."""
    return Response(prueba.PLANTILLA_CSV, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="ignis_csv_de_prueba.csv"'})


@router.post("/prueba", response_model=prueba.InformeImportacion)
async def importar_prueba(carga: CargaPrueba) -> prueba.InformeImportacion:
    """Ensaya la entrada de datos nuevos: mismo mapeo y unidades que la ingesta real, pero reversible y marcado como PRUEBA."""
    _permitir_prueba()
    try:
        return prueba.importar(carga.contenido)
    except prueba.ErrorImportacion as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error


@router.delete("/prueba")
async def quitar_prueba() -> dict[str, bool]:
    """Quita los datos de prueba y devuelve el catálogo al estado real."""
    _permitir_prueba()
    return {"quitado": prueba.quitar()}


@router.get("/ranking", response_model=RespuestaRanking)
async def ranking(
    entorno: Literal["iss", "luna", "marte", "traje"] = Query("luna"),
    area: Literal["prevencion", "deteccion", "supresion"] | None = Query(None),
    combustible: Literal["solido", "gas", "gota", "aerosol"] | None = Query(None),
    minimo: float = Query(0.0, ge=0, le=100),
    limite: int = Query(50, ge=1, le=100),
) -> RespuestaRanking:
    """Investigaciones filtradas y ordenadas por relevancia para el entorno, con desglose e interpretación."""
    _catalogo()
    res = inv.ranking(entorno, area, combustible, minimo, limite)
    return RespuestaRanking(estado=inv.cargar_catalogo_con_estado()[1], entorno=inv.ENTORNOS[entorno], total=len(res), resultados=res,
                            criterio="Heurística de diseño (O₂ 25, presión 10, combustible 20, seguridad 20, datos 15, gravedad 10), no validada por expertos.")


@router.get("/export")
async def exportar(formato: Literal["csv", "json"] = Query("csv"), conjunto: Literal["investigaciones", "anclas"] = Query("investigaciones")) -> Response:
    """Descarga datos estructurados para modelado predictivo (investigaciones o anclas de calibración)."""
    _catalogo()
    try:
        if formato == "csv":
            cuerpo, tipo = inv.exportar_csv(conjunto), "text/csv; charset=utf-8"
        else:
            import json
            cuerpo, tipo = json.dumps(inv.filas_exportacion(conjunto), ensure_ascii=False, indent=2), "application/json"
    except inv.ErrorCatalogo as error:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(error)) from error
    return Response(cuerpo, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="ignis_{conjunto}.{formato}"'})


@router.get("/gaps", response_model=list[inv.Hueco])
async def gaps() -> list[inv.Hueco]:
    """Qué falta: huecos de la base de la NASA y limitaciones propias de IGNIS."""
    _catalogo()
    return inv.huecos()


@router.get("/comparar")
async def comparar(ids: str = Query(..., pattern=r"^[a-z0-9-]+(,[a-z0-9-]+){1,5}$", description="2 a 6 ids separados por coma")) -> dict:
    """Similitudes y diferencias entre investigaciones."""
    _catalogo()
    try:
        return inv.comparar(ids.split(","))
    except KeyError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Investigación desconocida: {error.args[0]}") from error


@router.get("/aplicaciones-terrestres")
async def aplicaciones_terrestres() -> list[dict[str, str]]:
    """Aplicaciones en la Tierra citadas en el reto, con el área de seguridad relacionada y el porqué (criterio del equipo)."""
    return [{**a, "aviso": inv.APLICACIONES_AVISO} for a in inv.APLICACIONES_TERRESTRES]


@router.get("/{identificador}", response_model=ItemCatalogo)
async def detalle(identificador: str = IdInvestigacion) -> ItemCatalogo:
    """Ficha de una investigación con su relevancia por entorno."""
    _catalogo()
    i = inv.obtener(identificador)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Investigación desconocida: {identificador}")
    return ItemCatalogo(investigacion=i, relevancia=inv.puntajes_por_entorno(i))
