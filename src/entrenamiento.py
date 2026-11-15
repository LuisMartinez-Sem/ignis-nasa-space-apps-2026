"""Entrenamiento unificado de todos los componentes + reporte comparativo.

    python -m src.entrenamiento                    # RF + profundo + detector
    python -m src.entrenamiento --solo profundo    # solo un componente
    python -m src.entrenamiento --version 20261012-101500_ab12cd34   # dataset versionado

Escribe los pesos en `modelos/` y un reporte (`modelos/reporte.json`) que la API y el
HUD muestran tal cual: las cifras de la demo salen de aquí, nunca están hardcodeadas.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from src.config import Configuracion, obtener_configuracion
from src.data_loader import cargar_dataset
from src.evaluacion import MetricasEntrenamiento, PerfilLatencia, medir_latencia
from src.model import ModeloPropagacion, MotorPrediccion
from src.pipeline_datos import cargar_version, generar_y_versionar_sintetico
from src.utils import configurar_logging

logger = logging.getLogger(__name__)

COMPONENTES = ("rf", "profundo", "detector")
TAMANO_LOTE_LATENCIA = 100


class ReporteMotor(BaseModel):
    """Calidad y velocidad de un motor de propagación."""

    nombre: str
    metricas: MetricasEntrenamiento
    latencia_1_fila: PerfilLatencia
    latencia_lote: PerfilLatencia
    n_parametros: int | None = None


class ReporteDetector(BaseModel):
    """Calidad y velocidad del detector temporal."""

    metricas: dict
    benchmark: dict


class ReporteModelos(BaseModel):
    """Documento que viaja a la API y al HUD."""

    generado_utc: str
    origen_datos: str
    n_filas_dataset: int
    version_dataset: str | None
    motores: list[ReporteMotor]
    detector: ReporteDetector | None = None
    nota: str = (
        "Las métricas provienen de datos sintéticos semi-empíricos hasta cargar PSI; "
        "miden la mecánica del sistema, no la física real."
    )


def reporte_de_motor(motor: MotorPrediccion, muestra: pd.DataFrame, n_parametros: int | None = None) -> ReporteMotor:
    """Mide latencia en 1 fila y en lote, y agrega las métricas de entrenamiento."""
    if motor.metricas is None:
        raise ValueError(f"El motor '{motor.nombre}' no tiene métricas")
    una = muestra.iloc[:1]
    lote = muestra.iloc[:TAMANO_LOTE_LATENCIA]
    return ReporteMotor(
        nombre=motor.nombre,
        metricas=motor.metricas,
        latencia_1_fila=medir_latencia(lambda: motor.predecir(una), 30, 1),
        latencia_lote=medir_latencia(lambda: motor.predecir(lote), 20, len(lote)),
        n_parametros=n_parametros,
    )


def cargar_reporte(ruta: Path) -> ReporteModelos | None:
    """Lee el reporte guardado; None si no existe o es ilegible."""
    if not ruta.is_file():
        return None
    try:
        return ReporteModelos.model_validate_json(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Reporte ilegible", extra={"ruta": str(ruta)}, exc_info=True)
        return None


def entrenar(config: Configuracion, componentes: set[str], id_version: str | None = None) -> ReporteModelos:
    """Entrena los componentes pedidos, guarda pesos y reporte.

    Args:
        config: configuración de la aplicación.
        componentes: subconjunto de COMPONENTES.
        id_version: dataset versionado a usar; si es None se usa CSV configurado o sintético.
    """
    if id_version:
        datos, origen = cargar_version(config.directorio_datos, id_version), "real"
        from src.pipeline_datos import obtener_version
        origen = obtener_version(config.directorio_datos, id_version).origen
    else:
        datos, origen = cargar_dataset(
            config.ruta_dataset_csv, config.n_muestras_sinteticas, config.semilla_aleatoria
        )
        if origen == "sintetico":
            version = generar_y_versionar_sintetico(
                config.directorio_datos, config.n_muestras_sinteticas, config.semilla_aleatoria
            )
            id_version = version.id
    previo = cargar_reporte(config.ruta_reporte)
    motores: dict[str, ReporteMotor] = {m.nombre: m for m in (previo.motores if previo else [])}
    detector_reporte = previo.detector if previo else None
    muestra = datos.sample(n=min(len(datos), 200), random_state=1)

    if "rf" in componentes:
        rf = ModeloPropagacion(config.n_arboles, config.semilla_aleatoria)
        rf.entrenar(datos, origen)
        rf.guardar(config.ruta_modelo)
        motores["rf"] = reporte_de_motor(rf, muestra)
    if "profundo" in componentes:
        from src.modelo_profundo import ModeloProfundo

        profundo = ModeloProfundo(config.n_miembros_ensemble, semilla=config.semilla_aleatoria)
        profundo.entrenar(datos, origen, epocas=config.epocas_profundo)
        profundo.guardar(config.ruta_modelo_profundo)
        n_par = sum(p.numel() for p in profundo.red.parameters()) if profundo.red else None
        motores["profundo"] = reporte_de_motor(profundo, muestra, n_par)
    if "detector" in componentes:
        from src.benchmark_deteccion import evaluar_benchmark
        from src.detector_temporal import entrenar_detector

        detector = entrenar_detector(config.n_secuencias_detector, config.epocas_detector, config.semilla_aleatoria)
        detector.guardar(config.ruta_detector)
        informe = evaluar_benchmark(detector)
        assert detector.metricas is not None
        detector_reporte = ReporteDetector(
            metricas=detector.metricas.model_dump(), benchmark=informe.model_dump()
        )

    reporte = ReporteModelos(
        generado_utc=datetime.now(timezone.utc).isoformat(),
        origen_datos=origen,
        n_filas_dataset=len(datos),
        version_dataset=id_version,
        motores=[motores[k] for k in ("rf", "profundo") if k in motores],
        detector=detector_reporte,
    )
    config.ruta_reporte.parent.mkdir(parents=True, exist_ok=True)
    config.ruta_reporte.write_text(reporte.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Reporte escrito", extra={"ruta": str(config.ruta_reporte)})
    return reporte


def main(argv: list[str] | None = None) -> int:
    """CLI: devuelve el código de salida."""
    analizador = argparse.ArgumentParser(prog="entrenamiento", description=__doc__.split("\n")[0])
    analizador.add_argument("--solo", choices=COMPONENTES, action="append", help="Componente (repetible)")
    analizador.add_argument("--version", help="ID de dataset versionado (ver pipeline_datos versiones)")
    args = analizador.parse_args(argv)
    config = obtener_configuracion()
    configurar_logging(config.nivel_log)
    try:
        reporte = entrenar(config, set(args.solo or COMPONENTES), args.version)
    except Exception:  # CLI de nivel superior: registrar con traza y salir con error
        logger.exception("Entrenamiento fallido")
        return 1
    sys.stdout.write(reporte.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
