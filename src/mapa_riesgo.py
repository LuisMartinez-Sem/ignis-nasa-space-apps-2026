"""Mapa de riesgo atmosférico O₂ × presión con los entornos de exploración y la evidencia experimental verificable.

Muestra DÓNDE está cada hábitat sobre el índice del modelo y DÓNDE hay evidencia experimental conocida: la distancia entre
ambos es la brecha de conocimiento. El índice es del modelo sintético (calibrado, no validado) en microgravedad.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
from pydantic import BaseModel

from src.domain import RANGOS, CondicionesAmbiente
from src.investigaciones import ENTORNOS, RUTA_ANCLAS, cargar_catalogo_con_estado
from src.predictor import PredictorIgnis

logger = logging.getLogger(__name__)
N_O2, N_P = 25, 25
PPO2_TIERRA_KPA = 21.3  # 0,21 × 101,3 kPa


class Marcador(BaseModel):
    id: str
    nombre: str
    o2_pct: float
    presion_kpa: float
    tipo: str  # "entorno" | "evidencia"
    detalle: str
    dentro_del_dominio: bool


class Cobertura(BaseModel):
    """Región O₂ × presión que una investigación declara haber explorado (se actualiza sola al ingerir datos)."""

    id: str
    nombre: str
    o2_pct: tuple[float, float]
    presion_kpa: tuple[float, float]
    puntual: bool
    datos_en_psi: bool | None
    provisional: bool


class MapaRiesgo(BaseModel):
    o2_pct: list[float]
    presion_kpa: list[float]
    indice: list[list[float]]  # filas = presión, columnas = O₂
    condiciones_fijas: dict[str, Any]
    ppo2_tierra_kpa: float
    marcadores: list[Marcador]
    cobertura: list[Cobertura] = []
    huella: str = ""
    aviso: str


def _evidencia() -> list[Marcador]:
    """Puntos experimentales con O₂ y presión verificables (las anclas de entrenamiento con ambas condiciones)."""
    try:
        anclas = json.loads(RUTA_ANCLAS.read_text(encoding="utf-8"))["anclas"]
    except (OSError, KeyError, json.JSONDecodeError):
        logger.warning("Sin anclas para el mapa de evidencia")
        return []
    vistos: dict[tuple[float, float], list[str]] = {}
    for a in anclas:
        c = a.get("condiciones") or {}
        if a.get("uso") == "entrenamiento" and isinstance(c.get("fraccion_o2"), (int, float)) and isinstance(c.get("presion_kpa"), (int, float)):
            vistos.setdefault((round(c["fraccion_o2"] * 100, 1), float(c["presion_kpa"])), []).append(a["id"])
    return [Marcador(id=f"evidencia-{i}", nombre="Saffire-I (ancla del equipo)" if any("saffire-i" in x for x in ids) else ids[0], o2_pct=o2, presion_kpa=p,
                     tipo="evidencia", detalle="Condición de un ancla experimental publicada (no verificada por IGNIS): " + ", ".join(ids),
                     dentro_del_dominio=True) for i, ((o2, p), ids) in enumerate(vistos.items())]


def construir_mapa(predictor: PredictorIgnis, motor: str | None = None) -> MapaRiesgo:
    """Evalúa una rejilla O₂ × presión con el resto de condiciones fijas (vectorizado)."""
    o2 = np.linspace(RANGOS["fraccion_o2"][0], RANGOS["fraccion_o2"][1], N_O2)
    pr = np.linspace(RANGOS["presion_kpa"][0], RANGOS["presion_kpa"][1], N_P)
    fijas = {"velocidad_flujo_cm_s": 10.0, "temperatura_ambiente_k": 295.0, "espesor_combustible_mm": 0.2, "material": "sibal", "regimen_flujo": "opuesto"}
    lote = [CondicionesAmbiente(fraccion_o2=float(x), presion_kpa=float(p), **fijas) for p in pr for x in o2]
    res = predictor.evaluar_lote(lote, motor=motor)
    matriz = np.array([r.indice_riesgo for r in res]).reshape(N_P, N_O2)
    marcadores = [Marcador(id=e.id, nombre=e.nombre, o2_pct=e.o2_pct, presion_kpa=e.presion_kpa, tipo="entorno",
                           detalle=e.nota, dentro_del_dominio=RANGOS["fraccion_o2"][0] * 100 <= e.o2_pct <= RANGOS["fraccion_o2"][1] * 100
                           and RANGOS["presion_kpa"][0] <= e.presion_kpa <= RANGOS["presion_kpa"][1]) for e in ENTORNOS.values()]
    return MapaRiesgo(
        o2_pct=[round(float(x) * 100, 2) for x in o2], presion_kpa=[round(float(p), 2) for p in pr], indice=[[round(float(v), 1) for v in fila] for fila in matriz],
        condiciones_fijas=fijas, ppo2_tierra_kpa=PPO2_TIERRA_KPA, marcadores=[*marcadores, *_evidencia()],
        aviso="Índice del modelo sintético (calibrado, no validado) en microgravedad: potencial latente SI hubiera ignición. "
              "Los entornos fuera del dominio (p. ej. el traje) no se evalúan. Solo se marcan como evidencia las condiciones experimentales verificables.")


def construir_cobertura() -> tuple[list[Cobertura], str]:
    """Regiones O₂ × presión CONOCIDAS de las investigaciones (solo las que declaran ambos rangos completos) y la huella del catálogo.

    Se calcula en cada petición (es barato: el catálogo está en caché por fecha de modificación) para que el mapa
    refleje de inmediato cualquier dato ingerido, mientras la rejilla del modelo, que no cambia, sí se cachea.
    """
    lista, estado = cargar_catalogo_con_estado()
    nuevas = set(estado.nuevas_ingestadas)
    salida: list[Cobertura] = []
    for i in lista:
        o2, p = i.o2_pct, i.presion_kpa
        if o2.min is None or o2.max is None or p is None or p.min is None or p.max is None:
            continue
        salida.append(Cobertura(id=i.id, nombre=i.nombre, o2_pct=(o2.min, o2.max), presion_kpa=(p.min, p.max),
                                puntual=o2.min == o2.max and p.min == p.max, datos_en_psi=i.datos_en_psi, provisional=i.id in nuevas))
    return salida, estado.huella
