"""Comparativa RF vs. profundo con datos reales y línea verificable del pitch.

Flujo (todo con cifras calculadas, nunca escritas a mano):
    python -m src.reporte_psi --baseline           # fija el error de Saffire-I del modelo SINTÉTICO actual
    python -m src.reporte_psi --version <id>       # reentrena RF y profundo con la versión real y compara
Escribe `modelos/comparativa_real.json`, `docs/comparativa_real.md` y actualiza la línea de `docs/pitch.md`
entre los marcadores ``<!-- PITCH_LINEA -->``. Si no hay filas reales, la línea lo dice (0 filas).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from src.config import Configuracion, obtener_configuracion
from src.incidentes_historicos import CatalogoIncidentes
from src.ingesta_psi import ReporteCoberturaPsi, cargar_cobertura
from src.model import ErrorModelo, ModeloPropagacion
from src.pipeline_datos import cargar_version, listar_versiones, obtener_version
from src.predictor import PredictorIgnis
from src.simulador_incidentes import SimuladorIncidentes
from src.utils import configurar_logging

logger = logging.getLogger("ignis.reporte_psi")

ID_SAFFIRE = "saffire-2016-2024"
MARCA_INI, MARCA_FIN = "<!-- PITCH_LINEA -->", "<!-- /PITCH_LINEA -->"
NOMBRE_BASE = "linea_base_saffire.json"
PLANTILLA = ("Modelo entrenado con {saffire} filas de Saffire, {flex} de FLEX, {bass} de BASS. "
             "Recalibración en curso. Error Saffire-I reducido de {antes} a {despues}.")


class ErrorReporte(RuntimeError):
    """Falta un insumo para generar el reporte."""


class LineaBase(BaseModel):
    """Error de Saffire-I del modelo sintético (punto de partida del pitch)."""

    generado_utc: str
    motor: str
    error_abs_medio_pct: float
    n_con_medicion: int


class ResultadoMotor(BaseModel):
    nombre: str
    metricas: dict[str, float]
    error_saffire_i_pct: float | None = None


class Comparativa(BaseModel):
    generado_utc: str
    version_dataset: str
    sha256: str
    n_filas: int
    filas_por_experimento: dict[str, int] = Field(default_factory=dict)
    motores: list[ResultadoMotor]
    ganador_mae: str | None = None
    advertencias: list[str] = Field(default_factory=list)


def error_saffire_i(predictor: PredictorIgnis) -> tuple[float | None, int]:
    """Error absoluto medio (%) del predictor sobre las configuraciones Saffire-I medidas."""
    incidente = CatalogoIncidentes().obtener(ID_SAFFIRE)
    solo_i = incidente.model_copy(update={"experimentos": [
        e for e in incidente.experimentos if e.nombre.startswith("Saffire-I ·")]})
    metricas = SimuladorIncidentes(predictor).simular(solo_i).impacto.metricas
    return metricas.get("error_abs_medio_pct"), int(metricas.get("n_con_medicion", 0))


def _predictor_actual(config: Configuracion) -> tuple[PredictorIgnis, str]:
    rf = ModeloPropagacion.cargar(config.ruta_modelo)
    return PredictorIgnis(rf), rf.nombre


def fijar_linea_base(config: Configuracion, forzar: bool = False) -> LineaBase:
    """Registra el error de Saffire-I del modelo actual (sintético). No sobrescribe sin `forzar`."""
    ruta = config.directorio_datos / "processed" / NOMBRE_BASE
    if ruta.exists() and not forzar:
        return LineaBase.model_validate_json(ruta.read_text(encoding="utf-8"))
    predictor, motor = _predictor_actual(config)
    error, n = error_saffire_i(predictor)
    if error is None:
        raise ErrorReporte("Saffire-I no tiene mediciones para fijar la línea base")
    base = LineaBase(generado_utc=datetime.now(timezone.utc).isoformat(), motor=motor,
                     error_abs_medio_pct=round(error, 1), n_con_medicion=n)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(base.model_dump_json(indent=2), encoding="utf-8")
    return base


def filas_por_familia(cobertura: ReporteCoberturaPsi | None) -> dict[str, int]:
    """Suma filas válidas por familia (Saffire-*, FLEX*, BASS*). Sin cobertura → ceros."""
    total = {"saffire": 0, "flex": 0, "bass": 0}
    if cobertura is None:
        return total
    for exp, n in cobertura.filas_por_experimento.items():
        for familia in total:
            if exp.startswith(familia):
                total[familia] += n
    return total


def linea_pitch(cobertura: ReporteCoberturaPsi | None, base_pct: float | None, despues_pct: float | None) -> str:
    """Frase exacta pedida para el pitch; lo desconocido se muestra como [?], nunca se inventa."""
    f = filas_por_familia(cobertura)
    fmt = lambda v: "[?]%" if v is None else f"{v:.0f}%"  # noqa: E731
    return PLANTILLA.format(saffire=f["saffire"], flex=f["flex"], bass=f["bass"], antes=fmt(base_pct),
                            despues=fmt(despues_pct))


def actualizar_pitch(ruta: Path, linea: str) -> bool:
    """Sustituye el bloque entre marcadores (o lo crea al final). Devuelve True si cambió el archivo."""
    texto = ruta.read_text(encoding="utf-8")
    bloque = f"{MARCA_INI}\n**{linea}**\n{MARCA_FIN}"
    if MARCA_INI in texto:
        nuevo = re.sub(re.escape(MARCA_INI) + r".*?" + re.escape(MARCA_FIN), lambda _m: bloque, texto, flags=re.S)
    else:
        nuevo = texto.rstrip() + "\n\n" + bloque + "\n"
    if nuevo == texto:
        return False
    ruta.write_text(nuevo, encoding="utf-8")
    return True


def generar_comparativa(config: Configuracion, id_version: str) -> Comparativa:
    """Reentrena RF y profundo (partición agrupada) con una versión REAL y compara."""
    version = obtener_version(config.directorio_datos, id_version)
    if version.origen != "real":
        raise ErrorReporte(f"La versión {id_version} es '{version.origen}': la comparativa exige datos reales")
    datos = cargar_version(config.directorio_datos, id_version)
    cobertura = cargar_cobertura(config.directorio_datos, version)
    motores = [ModeloPropagacion(config.n_arboles, config.semilla_aleatoria)]
    advertencias: list[str] = []
    try:
        from src.modelo_profundo import ModeloProfundo
        motores.append(ModeloProfundo(config.n_miembros_ensemble, semilla=config.semilla_aleatoria))
    except ImportError:
        advertencias.append("PyTorch no disponible: solo se compara el RF")
    resultados: list[ResultadoMotor] = []
    for motor in motores:
        if motor.nombre == "profundo":
            metricas = motor.entrenar(datos, "real", epocas=config.epocas_profundo)
        else:
            metricas = motor.entrenar(datos, "real")
        error, _ = error_saffire_i(PredictorIgnis(motor))
        resultados.append(ResultadoMotor(nombre=motor.nombre, metricas=metricas.model_dump(), error_saffire_i_pct=error))
    if len(datos) < 200:
        advertencias.append(f"Solo {len(datos)} filas reales: las métricas tienen alta varianza; no sobreinterpretar.")
    ganador = min(resultados, key=lambda r: r.metricas["mae_velocidad_mm_s"]).nombre
    return Comparativa(
        generado_utc=datetime.now(timezone.utc).isoformat(), version_dataset=version.id, sha256=version.sha256,
        n_filas=len(datos), filas_por_experimento=cobertura.filas_por_experimento if cobertura else {},
        motores=resultados, ganador_mae=ganador, advertencias=advertencias)


def a_markdown(c: Comparativa, base: LineaBase | None) -> str:
    """Informe legible con las mismas cifras del JSON."""
    filas = "\n".join(
        f"| {m.nombre} | {m.metricas['r2_velocidad']:.3f} | {m.metricas['mae_velocidad_mm_s']:.3f} | "
        f"{m.metricas['auc_propagacion']:.3f} | {m.metricas['ece_propagacion']:.3f} | "
        f"{'—' if m.error_saffire_i_pct is None else f'{m.error_saffire_i_pct:.0f} %'} |" for m in c.motores)
    por_exp = ", ".join(f"{k}: {v}" for k, v in sorted(c.filas_por_experimento.items())) or "sin desglose"
    avisos = "".join(f"- {a}\n" for a in c.advertencias) or "- (sin advertencias)\n"
    return (f"# Comparativa RF vs. profundo con datos reales\n\nGenerado: {c.generado_utc}\n\n"
            f"Dataset `{c.version_dataset}` · SHA-256 `{c.sha256}` · {c.n_filas} filas ({por_exp}).\n\n"
            f"| Motor | R² vel. | MAE (mm/s) | AUC | ECE | Error Saffire-I |\n|---|---|---|---|---|---|\n{filas}\n\n"
            f"Menor MAE: **{c.ganador_mae}**. Línea base sintética de Saffire-I: "
            f"{'sin fijar' if base is None else f'{base.error_abs_medio_pct:.0f} %'}.\n\n"
            f"## Advertencias\n{avisos}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reporte_psi", description=__doc__.split("\n")[0])
    ap.add_argument("--baseline", action="store_true", help="fija la línea base con el modelo sintético actual")
    ap.add_argument("--forzar", action="store_true", help="sobrescribe la línea base")
    ap.add_argument("--version", help="ID de versión REAL para la comparativa")
    ap.add_argument("--pitch", type=Path, default=Path("docs/pitch.md"))
    args = ap.parse_args(argv)
    config = obtener_configuracion()
    configurar_logging(config.nivel_log)
    try:
        base = fijar_linea_base(config, args.forzar) if args.baseline or args.version else None
        cobertura = None
        despues = None
        if args.version:
            comparativa = generar_comparativa(config, args.version)
            (config.directorio_datos.parent / "modelos").mkdir(exist_ok=True)
            Path("modelos/comparativa_real.json").write_text(comparativa.model_dump_json(indent=2), encoding="utf-8")
            Path("docs/comparativa_real.md").write_text(a_markdown(comparativa, base), encoding="utf-8")
            cobertura = cargar_cobertura(config.directorio_datos, obtener_version(config.directorio_datos, args.version))
            despues = next((m.error_saffire_i_pct for m in comparativa.motores if m.nombre == comparativa.ganador_mae), None)
        elif not args.baseline:
            reales = [v for v in listar_versiones(config.directorio_datos) if v.origen == "real"]
            if reales:
                cobertura = cargar_cobertura(config.directorio_datos, reales[-1])
        linea = linea_pitch(cobertura, base.error_abs_medio_pct if base else None, despues)
        if args.pitch.exists():
            actualizar_pitch(args.pitch, linea)
        sys.stdout.write(linea + "\n")
    except (ErrorReporte, ErrorModelo, FileNotFoundError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
