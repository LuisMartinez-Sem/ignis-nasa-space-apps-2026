"""Escenarios de reproducción: telemetría guionizada evaluada con los modelos REALES de IGNIS.

Cada escenario define (a) condiciones del módulo por segundo y (b) un perfil de intensidad de llama
caliente/fría con el que se sintetizan los 6 canales de sensores a 10 Hz. Luego:
  - el predictor (RF/profundo) evalúa cada segundo → índice, probabilidades, llama fría;
  - el detector temporal TCN procesa los canales en streaming → alarma y latencia medida.
Nada del resultado se escribe a mano: el guion solo pone las entradas. Las entradas son ILUSTRATIVAS
(salvo las condiciones documentadas de Apollo 1, Saffire y las cronologías humanas de los incidentes).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from pydantic import BaseModel, Field, ValidationError

from src.domain import RANGOS, CondicionesAmbiente
from src.incidentes_historicos import CatalogoIncidentes, ErrorIncidente
from src.predictor import PredictorIgnis
from src.senales import CANALES, ESCALAS, FRECUENCIA_HZ

logger = logging.getLogger(__name__)

DT_S = 1.0 / FRECUENCIA_HZ
# Reacción térmica mínima (K sobre el ambiente) para considerar que hay un evento y no solo condiciones propensas
UMBRAL_REACCION_K = 50.0
NIVELES_ORDEN = {"NOMINAL": 0, "PRECAUCION": 1, "ALERTA": 2, "CRITICO": 3}
BASE = {"fraccion_o2": 0.21, "velocidad_flujo_cm_s": 10.0, "presion_kpa": 101.3, "temperatura_ambiente_k": 295.0,
        "espesor_combustible_mm": 0.3, "material": "sibal", "regimen_flujo": "opuesto", "temperatura_reaccion_k": 296.0}


class ErrorEscenario(ValueError):
    """Escenario inexistente o no reproducible."""


class Marca(BaseModel):
    """Evento marcado en una de las dos líneas de tiempo."""

    t_s: float
    texto: str
    confianza: str


class Fuego(BaseModel):
    """Ubicación SIMULADA del foco (el modelo no localiza; es parte del guion)."""

    sector: str
    x_m: float
    y_m: float
    nota: str = "Posición simulada del guion; IGNIS no localiza el foco con estos sensores."


class Frame(BaseModel):
    """Un segundo de la reproducción."""

    t_s: float
    condiciones: dict[str, Any]
    indice_riesgo: float | None = None
    nivel_riesgo: str | None = None
    velocidad_propagacion_mm_s: float | None = None
    incertidumbre_mm_s: float | None = None
    probabilidad_propagacion: float | None = None
    acciones_sugeridas: list[str] = Field(default_factory=list)
    origen_datos: str | None = None
    probabilidad_llama_fria: float | None = None
    estado_llama_fria: str | None = None
    fuera_de_dominio: bool = False
    advertencias: list[str] = Field(default_factory=list)
    p_evento: float | None = None
    clase_detector: str | None = None
    alarma_detector: bool = False
    canales: dict[str, float]
    canales_norm: dict[str, float]
    medicion_mm_s: float | None = None
    etiqueta: str | None = None
    evento_activo: bool = False  # hay reacción térmica o alarma del detector: el índice deja de ser solo 'potencial'


class Reproduccion(BaseModel):
    """Guion completo listo para reproducirse en el HUD."""

    id: str
    nombre: str
    descripcion: str
    duracion_s: float
    confianza: str
    advertencia: str
    fuego: Fuego | None
    frames: list[Frame]
    marcas_referencia: list[Marca]
    marcas_ignis: list[Marca]
    latencias_ms: dict[str, float | None]
    detector_disponible: bool


@dataclass(frozen=True)
class Escenario:
    """Definición de un guion (entradas, no resultados)."""

    id: str
    nombre: str
    descripcion: str
    duracion_s: float
    confianza: str
    advertencia: str
    condiciones: Callable[[float], dict[str, Any]]
    perfil: Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]  # t → (calor, fría) en 0..1
    fuego: Fuego | None = None
    referencia: list[Marca] = field(default_factory=list)
    picos: tuple[tuple[str, float, float, float], ...] = ()  # (canal, t_s, duración_s, amplitud)
    sin_modelo: bool = False
    etiquetas: Callable[[float], tuple[str | None, float | None]] | None = None


def _rampa(t: np.ndarray | float, t0: float, tau: float) -> np.ndarray | float:
    return 1.0 - np.exp(-np.clip(np.asarray(t) - t0, 0.0, None) / tau)


def _interp(puntos: list[tuple[float, float]]) -> Callable[[float], float]:
    xs, ys = zip(*puntos)
    return lambda t: float(np.interp(t, xs, ys))


def _con(**cambios: float | str) -> dict[str, Any]:
    return {**BASE, **cambios}


_ES_ILUSTRATIVO = "Entradas del guion ILUSTRATIVAS; los resultados (índice, alarma, latencia) los calculan los modelos de IGNIS."
_SECTOR = Fuego(sector="B-2", x_m=1.2, y_m=0.8)


def _definiciones() -> list[Escenario]:
    o2_esc = _interp([(0, 0.21), (10, 0.21), (60, 0.34), (90, 0.34)])
    tr_esc = _interp([(0, 296), (30, 296), (55, 700), (75, 1000), (90, 1000)])
    o2_mit = _interp([(0, 0.21), (10, 0.30), (35, 0.30), (60, 0.19), (90, 0.19)])
    tr_mit = _interp([(0, 296), (10, 296), (14, 1000), (35, 1000), (60, 420), (90, 320)])
    fr_mit = _interp([(0, 10), (35, 10), (50, 3), (90, 3)])
    tr_cf = _interp([(0, 296), (10, 296), (14, 1050), (26, 1000), (34, 690), (120, 690)])
    return [
        Escenario("nominal", "Nominal", "Atmósfera de la ISS, sin evento. IGNIS debe permanecer en NOMINAL.", 60, "ilustrativo",
                  _ES_ILUSTRATIVO, lambda t: _con(), lambda t: (t * 0, t * 0),
                  referencia=[Marca(t_s=0, texto="Inicio sin evento (guion)", confianza="ilustrativo")]),
        Escenario("escalada", "Escalada", "Fuga de O₂ gradual; la ignición llega cuando el aire está enriquecido.", 90, "ilustrativo",
                  _ES_ILUSTRATIVO, lambda t: _con(fraccion_o2=o2_esc(t), temperatura_reaccion_k=tr_esc(t)),
                  lambda t: (0.9 * _rampa(t, 55, 3.0), t * 0), fuego=_SECTOR,
                  referencia=[Marca(t_s=10, texto="Empieza la fuga de O₂ (guion)", confianza="ilustrativo"),
                              Marca(t_s=55, texto="Ignición (guion)", confianza="ilustrativo")]),
        Escenario("mitigacion", "Mitigación", "Fuego declarado, ventilación/supresión baja el O₂ y la llama se extingue.", 90, "ilustrativo",
                  _ES_ILUSTRATIVO, lambda t: _con(fraccion_o2=o2_mit(t), velocidad_flujo_cm_s=fr_mit(t), temperatura_reaccion_k=tr_mit(t)),
                  lambda t: (0.9 * _rampa(t, 12, 1.5) * np.exp(-np.clip(t - 35, 0, None) / 7.0), t * 0), fuego=_SECTOR,
                  referencia=[Marca(t_s=12, texto="Ignición (guion)", confianza="ilustrativo"),
                              Marca(t_s=35, texto="Se activa supresión (guion)", confianza="ilustrativo")]),
        Escenario("cool-flame", "Cool Flame residual", "Tras extinguir la llama caliente persiste una llama fría, invisible a cámara visible.", 120, "ilustrativo",
                  _ES_ILUSTRATIVO, lambda t: _con(presion_kpa=60.0, fraccion_o2=0.23, temperatura_reaccion_k=tr_cf(t)),
                  lambda t: (0.9 * _rampa(t, 12, 1.2) * np.exp(-np.clip(t - 24, 0, None) / 2.0), 0.7 * _rampa(t, 30, 4.0)), fuego=_SECTOR,
                  referencia=[Marca(t_s=12, texto="Llama caliente (guion)", confianza="ilustrativo"),
                              Marca(t_s=30, texto="Queda llama fría residual (guion)", confianza="ilustrativo")]),
    ]


def _escenario_mir(catalogo: CatalogoIncidentes) -> Escenario:
    inc = catalogo.obtener("mir-1997")
    pts = sorted(inc.telemetria_ilustrativa, key=lambda p: p.t_s)
    o2 = _interp([(p.t_s, p.fraccion_o2) for p in pts])
    tr = _interp([(p.t_s, p.temperatura_reaccion_k) for p in pts])
    base = inc.condiciones_base
    fijo = {"velocidad_flujo_cm_s": base.velocidad_flujo_cm_s, "presion_kpa": base.presion_kpa,
            "temperatura_ambiente_k": base.temperatura_ambiente_k, "espesor_combustible_mm": base.espesor_combustible_mm,
            "material": base.material.value, "regimen_flujo": base.regimen_flujo.value}
    ref = [Marca(t_s=e.t_s, texto=e.accion, confianza=e.confianza) for e in inc.timeline_humano if e.t_s is not None]
    return Escenario("mir-1997", "Incendio Mir 1997", inc.resumen, inc.duracion_simulacion_s, "ilustrativo",
                     inc.advertencia_modelo, lambda t: {**fijo, "fraccion_o2": o2(t), "temperatura_reaccion_k": tr(t)},
                     lambda t: (np.clip((np.interp(t, [p.t_s for p in pts], [p.temperatura_reaccion_k for p in pts]) - 295) / 855, 0, 1), t * 0),
                     fuego=Fuego(sector="Kvant-1", x_m=0.0, y_m=0.0, nota="Módulo documentado; posición exacta no disponible."),
                     referencia=ref)


def _escenario_iss(catalogo: CatalogoIncidentes) -> Escenario:
    inc = catalogo.obtener("iss-2015-falsa-alarma")
    ref = [Marca(t_s=e.t_s, texto=e.accion, confianza=e.confianza) for e in inc.timeline_humano
           if e.t_s is not None and e.t_s <= inc.duracion_simulacion_s]
    ref.append(Marca(t_s=float(inc.inicio_evento_s or 10), texto="Pico de UN solo sensor (traza sintética)", confianza="ilustrativo"))
    return Escenario("iss-2015", "Falsa alarma ISS 2015", inc.resumen, inc.duracion_simulacion_s, "ilustrativo",
                     inc.advertencia_modelo, lambda t: _con(), lambda t: (t * 0, t * 0), referencia=ref,
                     picos=(("co_ppm", 10.0, 0.3, 150.0),))


def _escenario_apollo(catalogo: CatalogoIncidentes) -> Escenario:
    inc = catalogo.obtener("apollo1-1967")
    c = inc.condiciones_base
    hist = {"fraccion_o2": c.fraccion_o2, "velocidad_flujo_cm_s": c.velocidad_flujo_cm_s, "presion_kpa": c.presion_kpa,
            "temperatura_ambiente_k": c.temperatura_ambiente_k, "espesor_combustible_mm": c.espesor_combustible_mm,
            "material": c.material.value, "regimen_flujo": c.regimen_flujo.value}
    ref = [Marca(t_s=e.t_s, texto=e.accion, confianza=e.confianza) for e in inc.timeline_humano if e.t_s is not None]
    return Escenario("apollo1-1967", "Apollo 1 (1967)", inc.resumen, inc.duracion_simulacion_s, "documentado",
                     inc.advertencia_modelo, lambda t: dict(hist), lambda t: (t * 0, t * 0), referencia=ref, sin_modelo=True)


def _escenario_saffire(catalogo: CatalogoIncidentes) -> Escenario:
    inc = catalogo.obtener("saffire-2016-2024")
    exps = inc.experimentos
    paso = 6.0

    def condiciones(t: float) -> dict[str, Any]:
        e = exps[min(int(t // paso), len(exps) - 1)]
        d = e.condiciones
        return {"fraccion_o2": d.fraccion_o2, "velocidad_flujo_cm_s": d.velocidad_flujo_cm_s, "presion_kpa": d.presion_kpa,
                "temperatura_ambiente_k": d.temperatura_ambiente_k, "espesor_combustible_mm": d.espesor_combustible_mm,
                "material": d.material.value, "regimen_flujo": d.regimen_flujo.value, "temperatura_reaccion_k": None}

    def etiquetas(t: float) -> tuple[str | None, float | None]:
        e = exps[min(int(t // paso), len(exps) - 1)]
        return e.nombre, (e.medicion.velocidad_propagacion_mm_s if e.medicion else None)

    ref = [Marca(t_s=i * paso, texto=e.nombre, confianza=(e.medicion.confianza if e.medicion else "supuesto")) for i, e in enumerate(exps)]
    return Escenario("saffire-2016-2024", "Saffire I–VI", inc.resumen, paso * len(exps), "modelo", inc.advertencia_modelo,
                     condiciones, lambda t: (t * 0, t * 0), referencia=ref, etiquetas=etiquetas)


def catalogo_escenarios(catalogo: CatalogoIncidentes | None = None) -> dict[str, Escenario]:
    """Todos los guiones disponibles, indexados por id."""
    catalogo = catalogo or CatalogoIncidentes()
    lista = _definiciones()
    try:
        lista += [_escenario_mir(catalogo), _escenario_iss(catalogo), _escenario_apollo(catalogo), _escenario_saffire(catalogo)]
    except ErrorIncidente as error:
        raise ErrorEscenario(f"Falta un incidente base: {error}") from error
    return {e.id: e for e in lista}


def sintetizar_senales(escenario: Escenario, semilla: int = 11) -> np.ndarray:
    """Canales (T, 6) en unidades físicas a 10 Hz, con la misma morfología que el generador de entrenamiento."""
    t = np.arange(int(round(escenario.duracion_s * FRECUENCIA_HZ))) * DT_S
    calor, fria = (np.asarray(x, dtype=float) * np.ones_like(t) for x in escenario.perfil(t))
    rng = np.random.default_rng(semilla)
    delta_t = 220.0 * fria + 900.0 * calor
    ir = np.clip(delta_t, 0, None) ** 1.5 / 1200.0 ** 1.5
    senales = np.stack([
        delta_t + rng.normal(0, 0.8, t.size), ir + rng.normal(0, 0.003, t.size), 0.8 * calor + rng.normal(0, 0.004, t.size),
        -0.4 * calor - 0.1 * fria + rng.normal(0, 0.003, t.size), 0.06 * (calor + fria) + rng.normal(0, 0.01, t.size),
        60.0 * calor + 20.0 * fria + rng.normal(0, 1.5, t.size)], axis=-1)
    for canal, t0, dur, amp in escenario.picos:
        sel = (t >= t0) & (t < t0 + dur)
        senales[sel, CANALES.index(canal)] += amp
    senales[:, [1, 2, 5]] = np.clip(senales[:, [1, 2, 5]], 0.0, None)
    return senales.astype(np.float32)


def trazar_detector(escenario: Escenario, detector: Any, semilla: int = 11) -> list[Any]:
    """Pasa los canales del escenario por el detector en streaming y devuelve cada `PasoDetector` (10 Hz).

    Permite medir tiempos con resolución de 0,1 s (la reproducción solo conserva 1 Hz).
    """
    flujo = detector.streaming(FRECUENCIA_HZ)
    return [flujo.paso(muestra) for muestra in sintetizar_senales(escenario, semilla)]


def _en_dominio(c: dict[str, Any]) -> bool:
    return all(RANGOS[k][0] <= float(c[k]) <= RANGOS[k][1] for k in ("fraccion_o2", "presion_kpa", "velocidad_flujo_cm_s",
                                                                       "temperatura_ambiente_k", "espesor_combustible_mm"))


def generar_reproduccion(escenario: Escenario, predictor: PredictorIgnis, detector: Any | None = None) -> Reproduccion:
    """Evalúa el guion con los modelos y devuelve frames a 1 Hz + marcas + latencias medidas."""
    n = int(escenario.duracion_s) + 1
    senales = sintetizar_senales(escenario)
    # --- Detector TCN en streaming (latencia medida por muestra)
    por_seg: list[dict[str, Any]] = [{"p": 0.0, "clase": None, "alarma": False, "nueva": False} for _ in range(n)]
    lat_tcn: list[float] = []
    if detector is not None:
        flujo = detector.streaming(FRECUENCIA_HZ)
        for i, muestra in enumerate(senales):
            paso = flujo.paso(muestra)
            lat_tcn.append(paso.latencia_ms)
            seg = por_seg[min(int(i // FRECUENCIA_HZ), n - 1)]
            seg.update(p=1.0 - paso.probabilidades.get("NOMINAL", 1.0),
                       clase=paso.clase, alarma=paso.alarma_activa, nueva=seg["nueva"] or paso.alarma_nueva)
    # --- Predictor por segundo (solo en dominio operativo)
    conds = [escenario.condiciones(float(t)) for t in range(n)]
    validas, indices = [], []
    if not escenario.sin_modelo:
        for i, c in enumerate(conds):
            if _en_dominio(c):
                try:
                    validas.append(CondicionesAmbiente(**{k: v for k, v in c.items() if v is not None}))
                    indices.append(i)
                except ValidationError:
                    continue
    inicio = time.perf_counter()
    evaluaciones = predictor.evaluar_lote(validas) if validas else []
    ms_modelo = (time.perf_counter() - inicio) * 1000.0 / max(1, len(validas))
    por_indice = dict(zip(indices, evaluaciones))

    frames: list[Frame] = []
    for i in range(n):
        j = min(int(round(i * FRECUENCIA_HZ)), senales.shape[0] - 1)
        canales = {k: round(float(v), 4) for k, v in zip(CANALES, senales[j])}
        norm = {k: round(float(v / e), 4) for k, v, e in zip(CANALES, senales[j], ESCALAS)}
        etiqueta, medicion = escenario.etiquetas(float(i)) if escenario.etiquetas else (None, None)
        f = Frame(t_s=float(i), condiciones=conds[i], canales=canales, canales_norm=norm, etiqueta=etiqueta, medicion_mm_s=medicion,
                  p_evento=round(por_seg[i]["p"], 4) if detector is not None else None, clase_detector=por_seg[i]["clase"],
                  alarma_detector=bool(por_seg[i]["alarma"]), fuera_de_dominio=escenario.sin_modelo or i not in por_indice and not _en_dominio(conds[i]))
        r = por_indice.get(i)
        if r is not None:
            f.indice_riesgo, f.nivel_riesgo = round(r.indice_riesgo, 1), r.nivel_riesgo.value
            f.velocidad_propagacion_mm_s, f.probabilidad_propagacion = round(r.velocidad_propagacion_mm_s, 3), round(r.probabilidad_propagacion, 4)
            f.probabilidad_llama_fria = None if r.probabilidad_llama_fria is None else round(r.probabilidad_llama_fria, 4)
            f.estado_llama_fria = r.estado_llama_fria.value
            f.fuera_de_dominio, f.advertencias = r.fuera_de_dominio, list(r.advertencias)
            f.incertidumbre_mm_s, f.acciones_sugeridas, f.origen_datos = round(r.incertidumbre_mm_s, 3), list(r.acciones_sugeridas), r.origen_datos
        t_reac = conds[i].get("temperatura_reaccion_k")
        f.evento_activo = bool(f.alarma_detector or (t_reac is not None and t_reac - float(conds[i]["temperatura_ambiente_k"]) >= UMBRAL_REACCION_K))
        frames.append(f)

    marcas = _marcas_ignis(frames, por_seg)
    lat = {"muestreo_ms": 1000.0 / FRECUENCIA_HZ, "tcn_ms_medio": float(np.mean(lat_tcn)) if lat_tcn else None,
           "tcn_ms_p95": float(np.percentile(lat_tcn, 95)) if lat_tcn else None, "modelo_ms_medio": ms_modelo if validas else None}
    return Reproduccion(id=escenario.id, nombre=escenario.nombre, descripcion=escenario.descripcion, duracion_s=float(n - 1),
                        confianza=escenario.confianza, advertencia=escenario.advertencia, fuego=escenario.fuego, frames=frames,
                        marcas_referencia=sorted(escenario.referencia, key=lambda m: m.t_s), marcas_ignis=marcas,
                        latencias_ms=lat, detector_disponible=detector is not None)


def _marcas_ignis(frames: list[Frame], por_seg: list[dict[str, Any]]) -> list[Marca]:
    """Hitos calculados: primer segundo en que el modelo o el detector reaccionan (nunca escritos a mano)."""
    marcas: list[Marca] = []
    visto: set[str] = set()
    for f, s in zip(frames, por_seg):
        if s["nueva"] and "tcn" not in visto:
            visto.add("tcn"); marcas.append(Marca(t_s=f.t_s, texto="Alarma del detector TCN", confianza="modelo"))
        if f.nivel_riesgo and f.evento_activo and NIVELES_ORDEN[f.nivel_riesgo] >= 1:
            for nivel in ("PRECAUCION", "ALERTA", "CRITICO"):
                if NIVELES_ORDEN[f.nivel_riesgo] >= NIVELES_ORDEN[nivel] and nivel not in visto:
                    visto.add(nivel); marcas.append(Marca(t_s=f.t_s, texto=f"Índice en {nivel}", confianza="modelo"))
        if f.evento_activo and f.estado_llama_fria in ("POSIBLE", "PROBABLE") and "fria" not in visto:
            visto.add("fria"); marcas.append(Marca(t_s=f.t_s, texto=f"Llama fría {f.estado_llama_fria}", confianza="modelo"))
    return sorted(marcas, key=lambda m: m.t_s)
