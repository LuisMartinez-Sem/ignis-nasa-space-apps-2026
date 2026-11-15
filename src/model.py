"""Motor Random Forest: velocidad (regresión) + probabilidad de propagar (clasificación).

Es el motor rápido de entrenar y robusto con pocos datos; entrega incertidumbre
como dispersión entre árboles. El motor profundo vive en `modelo_profundo.py` y
implementa el mismo protocolo (`MotorPrediccion`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from src.data_loader import COLUMNAS_ENTRADA
from src.envolvente import Envolvente
from src.evaluacion import MetricasEntrenamiento, calcular_metricas
from src.preprocessing import (
    COLUMNAS_CARACTERISTICAS,
    construir_matriz_caracteristicas,
    construir_objetivos,
    dividir_datos,
)

logger = logging.getLogger(__name__)

VERSION_MODELO = "0.2.0"


class ErrorModelo(RuntimeError):
    """Modelo no entrenado, archivo corrupto o datos de entrenamiento degenerados."""


@dataclass(frozen=True)
class PrediccionCruda:
    """Salida vectorizada de un motor, un elemento por fila de entrada."""

    velocidad_mm_s: np.ndarray
    incertidumbre_mm_s: np.ndarray
    probabilidad_propagacion: np.ndarray


@runtime_checkable
class MotorPrediccion(Protocol):
    """Contrato común: el predictor no sabe (ni necesita saber) qué hay detrás."""

    nombre: str
    origen_datos: str
    metricas: MetricasEntrenamiento | None
    envolvente: Envolvente

    @property
    def entrenado(self) -> bool:
        """True si el motor está listo para predecir."""
        ...

    def predecir(self, datos: pd.DataFrame) -> PrediccionCruda:
        """Predice en lote."""
        ...


class ModeloPropagacion:
    """Par regresor/clasificador Random Forest."""

    nombre = "rf"

    def __init__(self, n_arboles: int = 150, semilla: int = 42) -> None:
        self.n_arboles = n_arboles
        self.semilla = semilla
        self.regresor: RandomForestRegressor | None = None
        self.clasificador: RandomForestClassifier | None = None
        self.metricas: MetricasEntrenamiento | None = None
        self.origen_datos: str = "desconocido"
        self.envolvente: Envolvente = Envolvente()

    @property
    def entrenado(self) -> bool:
        """True si hay regresor y clasificador listos para predecir."""
        return self.regresor is not None and self.clasificador is not None

    def entrenar(self, datos: pd.DataFrame, origen_datos: str) -> MetricasEntrenamiento:
        """Entrena con la partición compartida `dividir_datos` (80/20).

        Args:
            datos: DataFrame ya validado (`data_loader.validar_dataframe`).
            origen_datos: 'real' o 'sintetico'; viaja con el modelo hasta la API.

        Raises:
            ErrorModelo: si el dataset no contiene ambas clases (propaga / no propaga).
        """
        entrenamiento, prueba = dividir_datos(datos, self.semilla)
        v_ent, p_ent = construir_objetivos(entrenamiento)
        v_pru, p_pru = construir_objetivos(prueba)
        if p_ent.min() == p_ent.max() or p_pru.min() == p_pru.max():
            raise ErrorModelo("El dataset solo contiene una clase de propagación")

        x_ent = construir_matriz_caracteristicas(entrenamiento).to_numpy(dtype=float)
        x_pru = construir_matriz_caracteristicas(prueba).to_numpy(dtype=float)
        self.regresor = RandomForestRegressor(
            n_estimators=self.n_arboles, min_samples_leaf=2,
            random_state=self.semilla, n_jobs=-1,
        ).fit(x_ent, v_ent)
        self.clasificador = RandomForestClassifier(
            n_estimators=self.n_arboles, min_samples_leaf=2,
            random_state=self.semilla, n_jobs=-1,
        ).fit(x_ent, p_ent)

        self._preparar_inferencia()
        self.metricas = calcular_metricas(
            v_pru, self.regresor.predict(x_pru), p_pru,
            self.clasificador.predict_proba(x_pru)[:, 1], len(x_ent),
        )
        self.origen_datos = origen_datos
        self.envolvente = Envolvente.desde_datos(datos, COLUMNAS_ENTRADA)
        logger.info("Modelo RF entrenado", extra=self.metricas.model_dump())
        return self.metricas

    def _preparar_inferencia(self) -> None:
        """Un solo hilo en inferencia: con lotes pequeños, lanzar hilos cuesta más que predecir."""
        if self.regresor is not None:
            self.regresor.n_jobs = 1
        if self.clasificador is not None:
            self.clasificador.n_jobs = 1

    def predecir(self, datos: pd.DataFrame) -> PrediccionCruda:
        """Predice en lote (vectorizado).

        Raises:
            ErrorModelo: si el modelo no está entrenado.
        """
        if self.regresor is None or self.clasificador is None:
            raise ErrorModelo("El modelo no está entrenado")
        x = construir_matriz_caracteristicas(datos).to_numpy(dtype=float)
        # Predicción por árbol: media = estimación, desviación = incertidumbre
        # tree_.predict evita la validación de entrada de cada árbol (150 llamadas por consulta)
        x32 = x.astype(np.float32)
        por_arbol = np.stack([arbol.tree_.predict(x32)[:, 0] for arbol in self.regresor.estimators_])
        indice_positivo = int(np.flatnonzero(self.clasificador.classes_ == 1)[0])
        probabilidad = self.clasificador.predict_proba(x)[:, indice_positivo]
        return PrediccionCruda(
            velocidad_mm_s=np.clip(por_arbol.mean(axis=0), 0.0, None),
            incertidumbre_mm_s=por_arbol.std(axis=0),
            probabilidad_propagacion=probabilidad,
        )

    def guardar(self, ruta: Path) -> None:
        """Serializa el modelo. Solo cargar archivos propios: joblib usa pickle."""
        if not self.entrenado:
            raise ErrorModelo("No se puede guardar un modelo sin entrenar")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "version": VERSION_MODELO,
                "columnas": list(COLUMNAS_CARACTERISTICAS),
                "regresor": self.regresor,
                "clasificador": self.clasificador,
                "metricas": self.metricas.model_dump() if self.metricas else None,
                "origen_datos": self.origen_datos,
                "envolvente": self.envolvente.model_dump(),
                "n_arboles": self.n_arboles,
                "semilla": self.semilla,
            },
            ruta,
        )
        logger.info("Modelo guardado", extra={"ruta": str(ruta)})

    @classmethod
    def cargar(cls, ruta: Path) -> ModeloPropagacion:
        """Carga un modelo guardado, verificando versión y columnas.

        Raises:
            ErrorModelo: si falta el archivo, está corrupto o es incompatible.
        """
        if not ruta.is_file():
            raise ErrorModelo(f"No existe el modelo: {ruta}")
        try:
            contenido = joblib.load(ruta)
            if contenido["version"] != VERSION_MODELO:
                raise ErrorModelo(f"Versión incompatible: {contenido['version']}")
            if contenido["columnas"] != list(COLUMNAS_CARACTERISTICAS):
                raise ErrorModelo("Las columnas del modelo no coinciden con el código actual")
            modelo = cls(contenido["n_arboles"], contenido["semilla"])
            modelo.regresor = contenido["regresor"]
            modelo.clasificador = contenido["clasificador"]
            modelo.origen_datos = contenido["origen_datos"]
            modelo.envolvente = Envolvente(**contenido["envolvente"])
            modelo._preparar_inferencia()
            if contenido["metricas"]:
                modelo.metricas = MetricasEntrenamiento(**contenido["metricas"])
        except ErrorModelo:
            raise
        except Exception as error:  # joblib puede lanzar casi cualquier cosa con un archivo roto
            logger.error("Modelo ilegible", extra={"ruta": str(ruta)}, exc_info=True)
            raise ErrorModelo(f"Modelo ilegible ({ruta.name}): {error}") from error
        logger.info("Modelo cargado", extra={"ruta": str(ruta)})
        return modelo
