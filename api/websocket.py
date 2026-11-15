"""WebSockets de tiempo real: evaluación bajo demanda y escenario demo para el HUD."""

from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from api.schemas import MensajeTelemetria
from src.senales import CANALES, TIPOS_EVENTO
from src.trazas import traza_representativa
from src.domain import CondicionesAmbiente, Material
from src.predictor import PredictorIgnis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tiempo-real"])

# Un mensaje de condiciones real pesa <500 B; el tope frena payloads abusivos
MAX_BYTES_MENSAJE = 4096

# Escenario demo (segundos): nominal → escalada → mitigación → llama fría residual
_T = [0.0, 10.0, 30.0, 45.0, 55.0, 60.0]
_FRACCION_O2 = [0.21, 0.21, 0.32, 0.32, 0.20, 0.20]
_FLUJO_CM_S = [10.0, 10.0, 14.0, 14.0, 2.0, 2.0]
_TEMP_REACCION_K = [300.0, 300.0, 1050.0, 1050.0, 720.0, 720.0]
DURACION_ESCENARIO_S = _T[-1]


def condiciones_escenario(t_s: float) -> CondicionesAmbiente:
    """Condiciones del escenario demo en el instante `t_s` (cíclico, 60 s)."""
    t = t_s % DURACION_ESCENARIO_S
    return CondicionesAmbiente(
        fraccion_o2=float(np.interp(t, _T, _FRACCION_O2)),
        velocidad_flujo_cm_s=float(np.interp(t, _T, _FLUJO_CM_S)),
        presion_kpa=101.3,
        temperatura_ambiente_k=295.0,
        espesor_combustible_mm=0.4,
        material=Material.SIBAL,
        temperatura_reaccion_k=float(np.interp(t, _T, _TEMP_REACCION_K)),
    )


def _predictor_de(websocket: WebSocket) -> PredictorIgnis | None:
    servicio = getattr(websocket.app.state, "servicio", None)
    return None if servicio is None else servicio.predictor


class LimiteConexiones:
    """Tope de conexiones WebSocket simultáneas (anti agotamiento de recursos)."""

    def __init__(self, maximo: int) -> None:
        self.maximo = maximo
        self.activas = 0

    def tomar(self) -> bool:
        if self.activas >= self.maximo:
            return False
        self.activas += 1
        return True

    def soltar(self) -> None:
        self.activas = max(0, self.activas - 1)


async def _aceptar(websocket: WebSocket) -> bool:
    """Acepta la conexión respetando el tope; devuelve False si se rechazó."""
    limite: LimiteConexiones | None = getattr(websocket.app.state, "limite_ws", None)
    await websocket.accept()
    if limite is not None and not limite.tomar():
        await websocket.close(code=1013, reason="Demasiadas conexiones")
        return False
    return True


def _liberar(websocket: WebSocket) -> None:
    limite: LimiteConexiones | None = getattr(websocket.app.state, "limite_ws", None)
    if limite is not None:
        limite.soltar()


async def _evaluar(
    predictor: PredictorIgnis, condiciones: CondicionesAmbiente, origen: str, t_s: float | None
) -> dict:
    """Evalúa en un hilo y devuelve el mensaje listo para `send_json`."""
    evaluacion = await asyncio.to_thread(predictor.evaluar, condiciones)
    mensaje = MensajeTelemetria(
        origen=origen, t_s=t_s, condiciones=condiciones, evaluacion=evaluacion
    )
    return mensaje.model_dump(mode="json")


@router.websocket("/ws/predict")
async def ws_predecir(websocket: WebSocket) -> None:
    """Recibe condiciones (JSON) y responde con la evaluación; errores no cierran el canal."""
    if not await _aceptar(websocket):
        return
    predictor = _predictor_de(websocket)
    if predictor is None:
        _liberar(websocket)
        await websocket.close(code=1013, reason="Modelo no disponible")
        return
    try:
        while True:
            texto = await websocket.receive_text()
            if len(texto.encode("utf-8")) > MAX_BYTES_MENSAJE:
                await websocket.send_json({"tipo": "error", "detalle": "Mensaje demasiado grande"})
                continue
            try:
                condiciones = CondicionesAmbiente.model_validate_json(texto)
            except ValidationError as error:
                detalle = json.loads(error.json(include_url=False, include_input=False))
                await websocket.send_json({"tipo": "error", "detalle": detalle})
                continue
            await websocket.send_json(await _evaluar(predictor, condiciones, "cliente", None))
    except WebSocketDisconnect:
        logger.info("Cliente /ws/predict desconectado")
    finally:
        _liberar(websocket)


@router.websocket("/ws/demo")
async def ws_demo(
    websocket: WebSocket, ritmo_hz: float = Query(2.0, ge=0.5, le=10.0)
) -> None:
    """Emite el escenario demo en bucle: permite desarrollar el HUD sin sensores."""
    if not await _aceptar(websocket):
        return
    predictor = _predictor_de(websocket)
    if predictor is None:
        _liberar(websocket)
        await websocket.close(code=1013, reason="Modelo no disponible")
        return
    t_s = 0.0
    try:
        while True:
            mensaje = await _evaluar(predictor, condiciones_escenario(t_s), "escenario_demo", t_s)
            await websocket.send_json(mensaje)
            t_s += 1.0 / ritmo_hz
            await asyncio.sleep(1.0 / ritmo_hz)
    except WebSocketDisconnect:
        logger.info("Cliente /ws/demo desconectado")
    finally:
        _liberar(websocket)


@router.websocket("/ws/sensores")
async def ws_sensores(
    websocket: WebSocket,
    tipo: str = Query("caliente", description="Tipo de traza sintética de sensores"),
    velocidad: float = Query(1.0, ge=0.5, le=20.0, description="Factor de tiempo (1 = tiempo real)"),
) -> None:
    """Reproduce una traza de 6 canales por el detector temporal, muestra a muestra.

    Es el 'cable de sensores': cuando haya hardware real, se sustituye la traza
    sintética por la lectura real sin cambiar el contrato del mensaje.
    """
    if not await _aceptar(websocket):
        return
    servicio = getattr(websocket.app.state, "servicio", None)
    detector = None if servicio is None else servicio.detector
    if detector is None or tipo not in TIPOS_EVENTO:
        _liberar(websocket)
        motivo = "Detector no disponible" if detector is None else "Tipo de traza inválido"
        await websocket.close(code=1013 if detector is None else 1008, reason=motivo)
        return
    traza = traza_representativa(tipo)
    espera_s = 1.0 / (traza.frecuencia_hz * velocidad)
    try:
        while True:  # bucle: al terminar la traza se reinicia con un detector limpio
            flujo = detector.streaming(traza.frecuencia_hz)
            for muestra in traza.senales:
                paso = await asyncio.to_thread(flujo.paso, muestra)
                await websocket.send_json({
                    "tipo": "sensores", "traza": tipo, "t_s": round(paso.t_s, 3),
                    "canales": dict(zip(CANALES, (round(float(v), 4) for v in muestra))),
                    "clase": paso.clase, "probabilidades": paso.probabilidades,
                    "alarma_activa": paso.alarma_activa, "alarma_nueva": paso.alarma_nueva,
                    "latencia_ms": round(paso.latencia_ms, 2), "t_evento_real_s": traza.t_inicio_s,
                })
                await asyncio.sleep(espera_s)
    except WebSocketDisconnect:
        logger.info("Cliente /ws/sensores desconectado")
    finally:
        _liberar(websocket)
