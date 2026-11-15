"""Modo Emergencia: contrato JSON consumido por `frontend/js/emergencias.js`."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status

from api.dependencias import obtener_catalogo, obtener_servicio
from src.emergencias import DESCARGO, Emergencia, ErrorEmergencia, construir_emergencia
from src.incidentes_historicos import CatalogoIncidentes, ErrorIncidente
from src.servicio_modelos import ServicioModelos

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/emergencias", tags=["emergencias"])
IdEmergencia = Path(..., pattern=r"^[a-z0-9][a-z0-9-]{1,59}$", max_length=60)
_cache: dict[str, Emergencia] = {}
IDS_PUBLICOS = ("mir-1997", "iss-2015", "columbus-cool-flame")  # exactamente estos 3, en este orden
INCIDENTE_CATALOGO = {"mir-1997": "mir-1997", "iss-2015": "iss-2015-falsa-alarma"}
_CONFIANZA_FRONT = {"documentado": "documentado", "aproximado": "aproximado"}  # el resto es no_verificado
_FUENTE_ACCION = "Reglas deterministas de IGNIS (apoyo a decisión)"


def _incidente(id_: str, ficha: Emergencia, catalogo: CatalogoIncidentes) -> dict[str, Any]:
    """Objeto `incidente` que espera el frontend (catálogo histórico, o construido para Columbus)."""
    if id_ in INCIDENTE_CATALOGO:
        try:
            datos = catalogo.obtener(INCIDENTE_CATALOGO[id_]).model_dump(mode="json")
        except ErrorIncidente as error:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(error)) from error
        datos["id"] = id_
        return datos
    return {
        "id": id_, "nombre": ficha.nombre, "fecha": None, "lugar": "Laboratorio Columbus (ISS), hipotético", "tipo": "hipotetico",
        "es_incendio": True, "modelo_aplicable": True,
        "resumen": "Llama fría invisible en un panel de Columbus. Escenario hipotético: no hay incidente real documentado.",
        "advertencia_modelo": "; ".join(ficha.advertencias), "inicio_evento_s": ficha.inicio_evento_s,
        "timeline_humano": [{"t_s": e.t_s, "accion": e.accion, "resultado": e.resultado,
                             "confianza": _CONFIANZA_FRONT.get(e.confianza, "no_verificado")} for e in ficha.timeline_humano],
        "supuestos_ignis": ficha.advertencias,
    }


def _ignis(id_: str, f: Emergencia) -> dict[str, Any]:
    supresion = next((e.t_s for e in f.timeline_ignis if "supresión" in e.accion.lower()), None)
    return {"deteccion_s": f.mediciones.get("deteccion_s", f.mediciones.get("descarte_s") if id_ == "iss-2015" else None),
            "deteccion_fuente": "TCN sobre telemetría sintética (medido por IGNIS)" if id_ != "iss-2015" else "",
            "supresion_s": supresion, "supresion_es_supuesto": True,
            "falsas_alarmas": (f.mediciones.get("alarmas") if id_ == "iss-2015" else None), "es_supuesto": True}


def _humano(id_: str) -> dict[str, Any] | None:
    if id_ != "mir-1997":
        return None  # el frontend lo deriva del incidente
    return {"deteccion_s": 0, "extincion_s": 90, "extincion_verificada": False,
            "fuente": "Mir 1997: detección visual inmediata, fuego de 90 s (extintores de espuma); duración total no verificada"}


def _acciones(f: Emergencia, ignis: dict[str, Any]) -> list[dict[str, Any]]:
    t_det = None if ignis["deteccion_s"] is None else f.inicio_evento_s + ignis["deteccion_s"]
    guia = [g for g in f.guia_copiloto if g != DESCARGO]
    salida = [{"id": f"g{i:02d}", "descripcion": g, "fuente": _FUENTE_ACCION, "fuente_verificada": False,
               "confianzas": ["supuesto"], "primer_t_s": t_det} for i, g in enumerate(guia)]
    return salida


@router.get("")
async def listar(catalogo: CatalogoIncidentes = Depends(obtener_catalogo)) -> list[dict[str, Any]]:
    """Resumen de las 3 emergencias (esquema de tarjeta del frontend)."""
    res = []
    for id_ in IDS_PUBLICOS:
        if id_ in INCIDENTE_CATALOGO:
            i = catalogo.obtener(INCIDENTE_CATALOGO[id_])
            res.append({"id": id_, "nombre": i.nombre, "fecha": i.fecha, "lugar": i.lugar, "tipo": str(i.tipo.value),
                        "es_incendio": i.es_incendio, "modelo_aplicable": i.modelo_aplicable, "resumen": i.resumen})
        else:
            res.append({"id": id_, "nombre": "Llama fría invisible en Columbus", "fecha": None,
                        "lugar": "Laboratorio Columbus (ISS), hipotético", "tipo": "hipotetico", "es_incendio": True,
                        "modelo_aplicable": True,
                        "resumen": "Llama fría sin luz visible en un panel de Columbus. Escenario hipotético."})
    return res


@router.get("/{identificador}")
async def detalle(identificador: str = IdEmergencia, servicio: ServicioModelos = Depends(obtener_servicio),
                  catalogo: CatalogoIncidentes = Depends(obtener_catalogo)) -> dict[str, Any]:
    """Detalle: `incidente`, `ignis`, `convencional`, `humano`, `simulacion.muestras` y `acciones`."""
    if identificador not in IDS_PUBLICOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Emergencia desconocida: {identificador}")
    if servicio.predictor is None or servicio.detector is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Modelo o detector no disponible")
    clave = f"{identificador}:{id(servicio.detector)}"
    if clave not in _cache:
        try:
            _cache[clave] = await asyncio.to_thread(construir_emergencia, identificador, servicio.predictor, servicio.detector)
        except ErrorEmergencia as error:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(error)) from error
    f = _cache[clave]
    ignis = _ignis(identificador, f)
    return {
        "incidente": _incidente(identificador, f, catalogo), "ignis": ignis,
        "convencional": None,  # sin datos propios: el frontend usa sus referencias opt-in
        "humano": _humano(identificador), "simulacion": {"muestras": f.muestras},
        "acciones": _acciones(f, ignis),
        "impacto": f.impacto.model_dump(), "mediciones": f.mediciones, "objetivos_diseno": f.objetivos_diseno,
        "capacidades_no_implementadas": f.capacidades_no_implementadas,
    }
