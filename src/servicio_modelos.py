"""Servicio de modelos: carga o entrena cada componente sin bloquear el arranque.

El RF (≈2 s) se prepara antes de aceptar tráfico: así la API siempre puede responder.
El motor profundo y el detector se cargan (o entrenan) en segundo plano; mientras
tanto sus endpoints informan `entrenando` en vez de fallar o bloquearse.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from enum import StrEnum

from src.config import Configuracion
from src.data_loader import cargar_dataset
from src.model import ErrorModelo
from src.predictor import PredictorIgnis, cargar_o_entrenar_predictor

logger = logging.getLogger(__name__)


class EstadoComponente(StrEnum):
    """Ciclo de vida de un componente opcional."""

    PENDIENTE = "pendiente"
    ENTRENANDO = "entrenando"
    LISTO = "listo"
    NO_DISPONIBLE = "no_disponible"
    ERROR = "error"


def torch_disponible() -> bool:
    """True si PyTorch está instalado (sin importarlo: importarlo tarda segundos)."""
    return importlib.util.find_spec("torch") is not None


class ServicioModelos:
    """Contenedor del predictor, el detector y el estado de cada componente."""

    def __init__(self, config: Configuracion) -> None:
        self.config = config
        self.predictor: PredictorIgnis | None = None
        self.detector = None  # DetectorTemporal | None (import perezoso de torch)
        self.estado: dict[str, EstadoComponente] = {
            "rf": EstadoComponente.PENDIENTE,
            "profundo": EstadoComponente.PENDIENTE,
            "detector": EstadoComponente.PENDIENTE,
        }
        self.detalle: dict[str, str] = {}
        self._tareas: list[asyncio.Task] = []

    # --- Carga síncrona (se ejecuta en hilos) --------------------------------------
    def _cargar_rf(self) -> None:
        self.estado["rf"] = EstadoComponente.ENTRENANDO
        self.predictor = cargar_o_entrenar_predictor(self.config)
        self.estado["rf"] = EstadoComponente.LISTO

    def _cargar_profundo(self) -> None:
        if not torch_disponible():
            self.estado["profundo"] = EstadoComponente.NO_DISPONIBLE
            self.detalle["profundo"] = "PyTorch no está instalado"
            return
        from src.modelo_profundo import ModeloProfundo

        try:
            self.estado["profundo"] = EstadoComponente.ENTRENANDO
            try:
                modelo = ModeloProfundo.cargar(self.config.ruta_modelo_profundo)
            except ErrorModelo as error:
                if not self.config.entrenar_profundo_al_iniciar:
                    self.estado["profundo"] = EstadoComponente.NO_DISPONIBLE
                    self.detalle["profundo"] = str(error)
                    return
                logger.warning("Se entrena el motor profundo", extra={"motivo": str(error)})
                datos, origen = cargar_dataset(
                    self.config.ruta_dataset_csv, self.config.n_muestras_sinteticas,
                    self.config.semilla_aleatoria,
                )
                modelo = ModeloProfundo(self.config.n_miembros_ensemble, semilla=self.config.semilla_aleatoria)
                modelo.entrenar(datos, origen, epocas=self.config.epocas_profundo)
                try:
                    modelo.guardar(self.config.ruta_modelo_profundo)
                except OSError:
                    logger.error("No se pudo guardar el motor profundo", exc_info=True)
            assert self.predictor is not None
            self.predictor.registrar_motor(modelo)
            self.estado["profundo"] = EstadoComponente.LISTO
        except Exception as error:  # el componente es opcional: nunca debe tumbar la API
            logger.exception("Motor profundo no disponible")
            self.estado["profundo"] = EstadoComponente.ERROR
            self.detalle["profundo"] = str(error)

    def _cargar_detector(self) -> None:
        if not torch_disponible():
            self.estado["detector"] = EstadoComponente.NO_DISPONIBLE
            self.detalle["detector"] = "PyTorch no está instalado"
            return
        from src.detector_temporal import DetectorTemporal, ErrorDetector, entrenar_detector

        try:
            self.estado["detector"] = EstadoComponente.ENTRENANDO
            try:
                self.detector = DetectorTemporal.cargar(self.config.ruta_detector)
            except ErrorDetector as error:
                if not self.config.entrenar_profundo_al_iniciar:
                    self.estado["detector"] = EstadoComponente.NO_DISPONIBLE
                    self.detalle["detector"] = str(error)
                    return
                logger.warning("Se entrena el detector", extra={"motivo": str(error)})
                self.detector = entrenar_detector(
                    self.config.n_secuencias_detector, self.config.epocas_detector,
                    self.config.semilla_aleatoria,
                )
                try:
                    self.detector.guardar(self.config.ruta_detector)
                except OSError:
                    logger.error("No se pudo guardar el detector", exc_info=True)
            self.estado["detector"] = EstadoComponente.LISTO
        except Exception as error:  # opcional: no tumba la API
            logger.exception("Detector no disponible")
            self.estado["detector"] = EstadoComponente.ERROR
            self.detalle["detector"] = str(error)

    # --- Arranque ------------------------------------------------------------------
    async def iniciar(self, esperar_opcionales: bool = False) -> None:
        """Prepara el RF (bloqueante) y lanza los componentes opcionales en segundo plano."""
        await asyncio.to_thread(self._cargar_rf)

        async def opcionales() -> None:
            # Secuencial: el detector y el motor profundo comparten CPU y torch
            await asyncio.to_thread(self._cargar_profundo)
            await asyncio.to_thread(self._cargar_detector)

        tarea = asyncio.create_task(opcionales())
        self._tareas.append(tarea)
        if esperar_opcionales:
            await tarea

    async def detener(self) -> None:
        """Cancela tareas de fondo pendientes al apagar la API."""
        for tarea in self._tareas:
            if not tarea.done():
                tarea.cancel()
        await asyncio.gather(*self._tareas, return_exceptions=True)

    def resumen(self) -> dict[str, dict[str, str]]:
        """Estado serializable para `/api/v1/modelo/estado`."""
        return {
            nombre: {"estado": estado.value, "detalle": self.detalle.get(nombre, "")}
            for nombre, estado in self.estado.items()
        }
