"""Incidentes históricos y comparativa humano vs. IGNIS."""

from __future__ import annotations

import asyncio
import logging

import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field

from api.dependencias import obtener_catalogo, obtener_servicio
from src.emergencias import construir_emergencia
from src.informe_pdf import EstadoVivo, generar_informe_pdf, generar_informe_vivo_pdf
from src.incidentes_historicos import CatalogoIncidentes, ErrorIncidente, Incidente, PATRON_ID, ResumenIncidente
from src.servicio_modelos import ServicioModelos
from src.simulador_incidentes import ComparativaIncidente, ErrorSimulacion, SimuladorIncidentes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/incidentes", tags=["incidentes"])

IdIncidente = Path(..., pattern=PATRON_ID.pattern, max_length=60)


def _incidente_o_404(catalogo: CatalogoIncidentes, identificador: str) -> Incidente:
    try:
        return catalogo.obtener(identificador)
    except ErrorIncidente as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get("", response_model=list[ResumenIncidente])
async def listar(catalogo: CatalogoIncidentes = Depends(obtener_catalogo)) -> list[ResumenIncidente]:
    """Lista de incidentes disponibles."""
    return catalogo.listar()


class EventoPropio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t_s: float | None = Field(None, ge=0, le=86400)
    accion: str = Field(..., min_length=3, max_length=300)
    resultado: str = Field("", max_length=300)


class IncidentePropio(BaseModel):
    """Formulario simplificado del investigador: IGNIS evalúa la atmósfera ANTES del evento (comparativa «precondición»)."""

    model_config = ConfigDict(extra="forbid")
    nombre: str = Field(..., min_length=3, max_length=80)
    fecha: str = Field("", max_length=30, description="Texto libre (p. ej. 1997-02-23); vacío = sin fecha")
    lugar: str = Field(..., min_length=2, max_length=120)
    resumen: str = Field(..., min_length=10, max_length=800)
    regimen_gravedad: Literal["microgravedad", "1g"] = "microgravedad"
    fraccion_o2: float = Field(..., ge=0.10, le=1.0)
    presion_kpa: float = Field(..., ge=10, le=250)
    fuente: str = Field(..., min_length=3, max_length=200, description="De dónde sale la información (obligatoria)")
    eventos: list[EventoPropio] = Field(default_factory=list, max_length=30)


@router.post("/propio", response_model=ResumenIncidente, status_code=status.HTTP_201_CREATED)
async def agregar_propio(datos: IncidentePropio, catalogo: CatalogoIncidentes = Depends(obtener_catalogo)) -> ResumenIncidente:
    """Agrega un incidente propio. Todo lo que aporta el usuario queda marcado «no verificado» y con su fuente declarada."""
    base = re.sub(r"[^a-z0-9]+", "-", datos.nombre.lower()).strip("-")[:40] or "incidente"
    identificador = f"propio-{base}-{int(time.time()) % 100000}"
    registro = {
        "id": identificador, "nombre": datos.nombre, "fecha": datos.fecha or "sin fecha", "lugar": datos.lugar, "regimen_gravedad": datos.regimen_gravedad,
        "tipo": "precondicion", "es_incendio": True, "resumen": datos.resumen, "modelo_aplicable": True,
        "advertencia_modelo": "Incidente aportado por el usuario: los datos no están verificados por IGNIS. El índice evalúa la atmósfera declarada, no reproduce el evento.",
        "duracion_simulacion_s": 60, "condiciones_base": {"fraccion_o2": datos.fraccion_o2, "velocidad_flujo_cm_s": 10.0, "presion_kpa": datos.presion_kpa,
            "temperatura_ambiente_k": 295.0, "espesor_combustible_mm": 0.3, "material": "sibal", "regimen_flujo": "opuesto"},
        "timeline_humano": [{"t_s": e.t_s, "accion": e.accion, "resultado": e.resultado, "categoria": "contexto", "confianza": "no_verificado", "fuente": 1} for e in datos.eventos],
        "supuestos_ignis": ["Material SIBAL, 10 cm/s y 295 K por defecto: el usuario no los declaró."],
        "fuentes": [{"id": 1, "titulo": datos.fuente, "organizacion": "Aportado por el usuario", "fiabilidad": "baja", "nota": "No verificado por IGNIS."}],
    }
    try:
        inc = catalogo.agregar_propio(registro)
    except ErrorIncidente as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    return next(r for r in catalogo.listar() if r.id == inc.id)


@router.delete("/propio/{identificador}", status_code=status.HTTP_204_NO_CONTENT)
async def quitar_propio(identificador: str = Path(..., max_length=80), catalogo: CatalogoIncidentes = Depends(obtener_catalogo)) -> Response:
    """Quita un incidente propio (los incidentes base no se pueden quitar)."""
    try:
        catalogo.quitar_propio(identificador)
    except ErrorIncidente as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{identificador}", response_model=Incidente)
async def detalle(
    identificador: str = IdIncidente, catalogo: CatalogoIncidentes = Depends(obtener_catalogo)
) -> Incidente:
    """Ficha completa: cronología documentada, fuentes y supuestos."""
    return _incidente_o_404(catalogo, identificador)


@router.get("/{identificador}/simular", response_model=ComparativaIncidente)
async def simular(
    identificador: str = IdIncidente,
    catalogo: CatalogoIncidentes = Depends(obtener_catalogo),
    servicio: ServicioModelos = Depends(obtener_servicio),
) -> ComparativaIncidente:
    """Comparativa contrafactual (ventana de oportunidad vs. reacción de IGNIS)."""
    incidente = _incidente_o_404(catalogo, identificador)
    if servicio.predictor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo no disponible")
    simulador = SimuladorIncidentes(servicio.predictor, servicio.detector)
    try:
        return await asyncio.to_thread(simulador.simular, incidente)
    except ErrorSimulacion as error:
        # El detector se entrena en segundo plano: el cliente puede reintentar
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error


_EMERGENCIA_DE_INCIDENTE = {"mir-1997": "mir-1997", "iss-2015-falsa-alarma": "iss-2015"}


async def _emergencia_equivalente(identificador: str, servicio: ServicioModelos):
    """Ficha de Modo Emergencia asociada (supresión simulada y guía del copiloto); None si no existe o no se puede calcular."""
    id_emergencia = _EMERGENCIA_DE_INCIDENTE.get(identificador)
    if id_emergencia is None or servicio.predictor is None or servicio.detector is None:
        return None
    try:
        return await asyncio.to_thread(construir_emergencia, id_emergencia, servicio.predictor, servicio.detector)
    except Exception:  # noqa: BLE001 (dato auxiliar)
        logger.warning("Sin ficha de emergencia para el informe", exc_info=True)
        return None


@router.get("/{identificador}/reporte_pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
async def reporte_pdf(
    identificador: str = IdIncidente,
    catalogo: CatalogoIncidentes = Depends(obtener_catalogo),
    servicio: ServicioModelos = Depends(obtener_servicio),
) -> Response:
    """Informe forense en PDF: cronología, reacción de IGNIS, impacto contrafactual y supuestos."""
    comparativa = await simular(identificador, catalogo, servicio)
    emergencia = await _emergencia_equivalente(identificador, servicio)
    try:
        pdf = await asyncio.to_thread(generar_informe_pdf, comparativa, emergencia)
    except Exception as error:  # noqa: BLE001 (el informe nunca debe devolver 500 sin contexto)
        logger.exception("Fallo al generar el PDF", extra={"id": identificador})
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se pudo generar el informe PDF") from error
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="ignis_informe_{identificador}.pdf"'})


@router.post("/reporte_pdf_live", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
async def reporte_pdf_live(estado: EstadoVivo) -> Response:
    """'Caja Negra' del estado actual del simulador: recibe el estado del HUD y devuelve el PDF."""
    try:
        pdf = await asyncio.to_thread(generar_informe_vivo_pdf, estado)
    except Exception as error:  # noqa: BLE001
        logger.exception("Fallo al generar el PDF en vivo")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No se pudo generar el informe PDF") from error
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="ignis_caja_negra.pdf"'})
