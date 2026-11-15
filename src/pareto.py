"""Análisis de Frontera de Pareto para priorización de experimentos.

Cada investigación del catálogo se coloca en un plano de dos ejes:

* **Riesgo (y, 0-100)**: índice del modelo IGNIS (sintético, calibrado, NO validado) en el punto de operación de la
  investigación. Los campos de O₂/presión que la investigación declara se usan tal cual (punto medio de su rango, recortado
  al dominio del modelo); los que se desconocen se INFIEREN del entorno objetivo y se marcan como tales. Además se calcula un
  intervalo [y_bajo, y_alto] evaluando las esquinas de la caja de incertidumbre (campo desconocido = todo el dominio).
* **Evidencia (x, 0-100)**: cuánta información verificable respalda a la investigación (O₂, presión, flujo, datos en PSI,
  gravedad). Cada componente es «verificado», «inferido/parcial» o «desconocido» y nunca se inventa.

Una investigación A **domina** a B si A tiene riesgo ≥ y evidencia ≤ que B (y al menos una estricta): A es igual o más
peligrosa y está igual o peor documentada. La **frontera de Pareto** (capa 1) son las no dominadas: los experimentos más
críticos (alto riesgo, baja evidencia). Las capas siguientes se obtienen por ordenamiento no dominado (estilo NSGA-II).

Todo es determinista y explicable; los pesos de evidencia son criterios de diseño, no resultados experimentales.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np

from pydantic import BaseModel, Field

from src.domain import RANGOS, CondicionesAmbiente
from src.investigaciones import ENTORNOS, Investigacion, Rango, cargar_catalogo_con_estado, puntuar, EstadoCatalogo
from src.predictor import PredictorIgnis

logger = logging.getLogger(__name__)

NOMBRE_ANALISIS = "Análisis de Frontera de Pareto para priorización de experimentos"
FLUJO_DEFECTO_CM_S = 10.0  # mismo valor por defecto que el Monitor; solo se usa si la investigación no declara flujo
CORTE_RIESGO = 50.0  # cuadrante «alto riesgo»
CORTE_EVIDENCIA = 40.0  # cuadrante «baja evidencia»
# Peso de cada componente de evidencia (suman 100). Criterio de diseño: los datos en PSI son lo que más reduce la incertidumbre.
PESOS_EVIDENCIA = {"o2": 25.0, "presion": 20.0, "flujo": 10.0, "datos_psi": 30.0, "gravedad": 15.0}
EntornoPareto = Literal["iss", "luna", "marte"]
EjeY = Literal["riesgo", "relevancia", "incertidumbre"]
# Eje vertical elegible: la frontera se recalcula con el mismo criterio de dominancia (más y, menos evidencia = más crítico).
EJES_Y = {
    "riesgo": ("Nivel de riesgo del modelo (0-100)", "mayor = más potencial de propagación"),
    "relevancia": ("Relevancia para el entorno (0-100)", "mayor = más pertinente para el entorno elegido (puntaje del ranking)"),
    "incertidumbre": ("Incertidumbre del riesgo (puntos)", "mayor = más riesgo por descubrir (ancho del intervalo del modelo)"),
}


class ComponenteEvidencia(BaseModel):
    campo: str
    peso: float
    aporte: float
    estado: Literal["verificado", "parcial", "desconocido"]
    motivo: str


class PuntoPareto(BaseModel):
    id: str
    nombre: str
    familia: str
    x: float = Field(..., ge=0, le=100, description="Evidencia (0-100)")
    y: float = Field(..., ge=0, le=100, description="Riesgo del modelo en el punto de operación (0-100)")
    y_bajo: float = Field(..., ge=0, le=100)
    y_alto: float = Field(..., ge=0, le=100)
    capa: int = Field(..., ge=1, description="1 = frontera de Pareto")
    en_frontera: bool
    cuadrante: Literal["critico", "alto_riesgo_documentado", "bajo_riesgo_sin_evidencia", "bajo_riesgo_documentado"]
    prioridad: float = Field(..., ge=0, le=100, description="Riesgo sin cubrir = riesgo × (1 − evidencia/100)")
    relevancia: float = Field(..., ge=0, le=100, description="Puntaje del ranking del SI Dashboard para el entorno")
    riesgo: float = Field(..., ge=0, le=100, description="Índice de riesgo del modelo (siempre presente, sea cual sea el eje Y elegido)")
    incertidumbre: float = Field(..., ge=0, le=100, description="Ancho P10-P90 del riesgo bajo la incertidumbre de O₂ y presión (puntos)")
    riesgo_medio: float = Field(..., ge=0, le=100, description="Media del índice sobre la caja de incertidumbre (rejilla 5×5 uniforme)")
    p_frontera: float = Field(..., ge=0, le=1, description="Probabilidad (Monte Carlo) de estar en la frontera al muestrear el riesgo dentro de su incertidumbre")
    dominados: int = Field(..., ge=0, description="Cuántas investigaciones domina esta (más crítica que ellas)")
    provisional: bool = Field(False, description="True si la investigación llegó por ingesta y aún no está catalogada")
    operacion: dict[str, float | None]
    inferidos: list[str]
    fuera_de_dominio: bool
    extrapolacion_combustible: bool = Field(..., description="True si la investigación no usa combustibles sólidos: el modelo solo se calibró con sólidos")
    evidencia_detalle: list[ComponenteEvidencia]
    lectura: str


class PuntoLinea(BaseModel):
    x: float
    y: float


class Ejes(BaseModel):
    id: str
    nombre: str
    min: float
    max: float
    sentido: str


class RespuestaPareto(BaseModel):
    titulo: str
    estado: EstadoCatalogo
    entorno: str
    eje_y: str
    ejes: dict[str, Ejes]
    cortes: dict[str, float]
    puntos: list[PuntoPareto]
    frontera: list[str]
    linea_frontera: list[PuntoLinea]
    codo: str | None
    hipervolumen: float = Field(..., ge=0, le=1, description="Fracción del plano dominada por el conjunto (0-1)")
    metodologia: list[str]
    supuestos: list[str]
    aviso: str


# ----------------------------------------------------------------------------------------------- evidencia
def _evidencia(inv: Investigacion) -> tuple[float, list[ComponenteEvidencia]]:
    """Puntaje de evidencia 0-100 y su desglose (cada componente es verificado, parcial o desconocido)."""
    comp: list[ComponenteEvidencia] = []

    def añadir(campo: str, fraccion: float, estado: Literal["verificado", "parcial", "desconocido"], motivo: str) -> None:
        peso = PESOS_EVIDENCIA[campo]
        comp.append(ComponenteEvidencia(campo=campo, peso=peso, aporte=round(peso * fraccion, 2), estado=estado, motivo=motivo))

    o2 = inv.o2_pct
    if o2.min is not None and o2.max is not None:
        añadir("o2", 1.0, "verificado", f"O₂ declarado {o2.min:g}-{o2.max:g} %")
    elif o2.min is not None or o2.max is not None:
        añadir("o2", 0.5, "parcial", "solo se conoce un extremo del rango de O₂")
    else:
        añadir("o2", 0.0, "desconocido", "O₂ de las pruebas no verificado")
    p = inv.presion_kpa
    if p is not None and (p.min is not None or p.max is not None):
        añadir("presion", 1.0 if p.min is not None and p.max is not None else 0.5, "verificado" if p.min is not None and p.max is not None else "parcial", "presión declarada")
    else:
        añadir("presion", 0.0, "desconocido", "presión de las pruebas no verificada")
    f = inv.flujo_cm_s
    if f is not None and f.min is not None and f.max is not None:
        añadir("flujo", 1.0, "verificado", f"flujo {f.min:g}-{f.max:g} cm/s")
    else:
        añadir("flujo", 0.0, "desconocido", "flujo de las pruebas no verificado")
    añadir("datos_psi", {True: 1.0, False: 0.15, None: 0.0}[inv.datos_en_psi], {True: "verificado", False: "parcial", None: "desconocido"}[inv.datos_en_psi],
           {True: "hay datos publicados en PSI", False: "experimento sin datos en PSI todavía", None: "disponibilidad en PSI no verificada"}[inv.datos_en_psi])
    g = {"microgravedad": 1.0, "parcial_emulada": 0.5, "parcial_pendiente": 0.0, "desconocida": 0.0}[inv.gravedad]
    añadir("gravedad", g, "verificado" if g == 1.0 else "parcial" if g > 0 else "desconocido",
           {"microgravedad": "régimen de microgravedad (el del modelo)", "parcial_emulada": "gravedad parcial solo emulada", "parcial_pendiente": "gravedad parcial pendiente: sin datos", "desconocida": "régimen de gravedad no declarado"}[inv.gravedad])
    return round(sum(c.aporte for c in comp), 1), comp


# ----------------------------------------------------------------------------------------------- riesgo
def _intervalo(r: Rango | None, dominio: tuple[float, float], escala: float = 1.0) -> tuple[float, float] | None:
    """Rango declarado recortado al dominio (None si la investigación no declara nada). `escala` convierte unidades."""
    if r is None or (r.min is None and r.max is None):
        return None
    lo = dominio[0] if r.min is None else r.min * escala
    hi = dominio[1] if r.max is None else r.max * escala
    lo, hi = max(dominio[0], min(lo, dominio[1])), max(dominio[0], min(hi, dominio[1]))
    return (lo, hi) if lo <= hi else (hi, lo)


def _condiciones(o2_frac: float, p_kpa: float, flujo: float) -> CondicionesAmbiente:
    return CondicionesAmbiente(fraccion_o2=o2_frac, presion_kpa=p_kpa, velocidad_flujo_cm_s=flujo, temperatura_ambiente_k=295.0,
                               espesor_combustible_mm=0.2, material="sibal", regimen_flujo="opuesto")


def _plan_riesgo(inv: Investigacion, entorno: str) -> dict:
    """Define el punto central y las esquinas de la caja de incertidumbre de una investigación (sin evaluar el modelo)."""
    env = ENTORNOS[entorno]
    dom_o2 = (RANGOS["fraccion_o2"][0], RANGOS["fraccion_o2"][1])
    dom_p = (RANGOS["presion_kpa"][0], RANGOS["presion_kpa"][1])
    r_o2 = _intervalo(inv.o2_pct, dom_o2, 0.01)
    r_p = _intervalo(inv.presion_kpa, dom_p)
    r_f = inv.flujo_cm_s
    flujo = (r_f.min + r_f.max) / 2 if r_f and r_f.min is not None and r_f.max is not None else FLUJO_DEFECTO_CM_S
    inferidos: list[str] = []
    if r_o2 is None:
        inferidos.append("o2_pct")
    if r_p is None:
        inferidos.append("presion_kpa")
    if r_f is None or r_f.min is None or r_f.max is None:
        inferidos.append("flujo_cm_s")
    # Un campo parcialmente conocido (p. ej. solo el máximo) también es inferido en su otro extremo.
    if inv.o2_pct.min is None and inv.o2_pct.max is not None:
        inferidos.append("o2_pct (extremo inferior)")
    centro_o2 = (r_o2[0] + r_o2[1]) / 2 if r_o2 and inv.o2_pct.min is not None else (min(max(env.o2_pct / 100, dom_o2[0]), dom_o2[1]))
    centro_p = (r_p[0] + r_p[1]) / 2 if r_p else min(max(env.presion_kpa, dom_p[0]), dom_p[1])
    caja_o2 = r_o2 if r_o2 else dom_o2
    caja_p = r_p if r_p else dom_p
    valores_o2 = [v / 100 for v in (inv.o2_pct.min, inv.o2_pct.max) if v is not None]
    valores_p = [v for v in ((inv.presion_kpa.min, inv.presion_kpa.max) if inv.presion_kpa else ()) if v is not None]
    fuera = any(not dom_o2[0] <= v <= dom_o2[1] for v in valores_o2) or any(not dom_p[0] <= v <= dom_p[1] for v in valores_p)
    return {"centro": (centro_o2, centro_p, flujo), "caja_o2": caja_o2, "caja_p": caja_p, "inferidos": inferidos, "fuera": fuera}


# ----------------------------------------------------------------------------------------------- Pareto
N_REJ = 5  # rejilla 5×5 sobre la caja de incertidumbre (25 evaluaciones del modelo por investigación)
SEMILLA_MC = 20261113


def _p_frontera(x: list[float], muestras: list[np.ndarray], y_fijo: list[float], remuestrear: bool) -> np.ndarray:
    """Probabilidad de que cada punto esté en la frontera de Pareto (máx. y, mín. evidencia) al incluir la incertidumbre.

    Monte Carlo determinista (semilla fija): en cada sorteo el riesgo de cada investigación se toma al azar de su propia
    rejilla de incertidumbre (equiprobable); la evidencia es exacta. Con `remuestrear=False` (ejes sin incertidumbre) el
    resultado es 0/1. El número de sorteos se limita para que el coste N²·D se mantenga acotado con catálogos grandes.
    """
    n = len(x)
    if n == 0:
        return np.zeros(0)
    xs = np.asarray(x, dtype=float)
    d = max(50, min(1000, int(2_000_000 // max(1, n * n)))) if remuestrear else 1
    rng = np.random.default_rng(SEMILLA_MC)
    if remuestrear:
        ys = np.stack([m[rng.integers(0, len(m), size=d)] for m in muestras], axis=1)  # (D, N)
    else:
        ys = np.asarray(y_fijo, dtype=float)[None, :]
    mayor_o_igual = ys[:, :, None] >= ys[:, None, :]  # [d, j, i]: y_j ≥ y_i
    menor_o_igual = (xs[:, None] <= xs[None, :])[None]  # [., j, i]: x_j ≤ x_i
    estricto = (ys[:, :, None] > ys[:, None, :]) | (xs[:, None] < xs[None, :])[None]
    domina = mayor_o_igual & menor_o_igual & estricto
    idx = np.arange(n)
    domina[:, idx, idx] = False
    return (~domina.any(axis=1)).mean(axis=0)


def _domina(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """a = (evidencia, riesgo). A domina a B si es ≥ en riesgo y ≤ en evidencia, con alguna desigualdad estricta."""
    return a[1] >= b[1] and a[0] <= b[0] and (a[1] > b[1] or a[0] < b[0])


def capas_no_dominadas(pares: list[tuple[float, float]]) -> list[int]:
    """Ordenamiento no dominado: capa 1 = frontera de Pareto; cada capa siguiente es la frontera del resto."""
    capas = [0] * len(pares)
    restantes = set(range(len(pares)))
    capa = 1
    while restantes:
        frente = {i for i in restantes if not any(_domina(pares[j], pares[i]) for j in restantes if j != i)}
        for i in frente:
            capas[i] = capa
        restantes -= frente
        capa += 1
    return capas


def hipervolumen(pares: list[tuple[float, float]]) -> float:
    """Fracción del cuadrado [0,100]² dominada por el conjunto, con referencia (evidencia=100, riesgo=0).

    Es el área bajo la envolvente max{riesgo_i : evidencia_i ≤ e} para e ∈ [0,100]. Mide cuánto del espacio «riesgo sin cubrir»
    ocupa el conjunto: cada dato nuevo que desplace puntos a la derecha lo reduce.
    """
    if not pares:
        return 0.0
    area, mejor, previo = 0.0, 0.0, 0.0
    for e, r in sorted(pares):
        area += mejor * (e - previo)
        mejor, previo = max(mejor, r), e
    area += mejor * (100.0 - previo)
    return round(area / 10000.0, 4)


def _cuadrante(x: float, y: float, corte_y: float = CORTE_RIESGO) -> str:
    alto, baja = y >= corte_y, x < CORTE_EVIDENCIA
    return "critico" if alto and baja else "alto_riesgo_documentado" if alto else "bajo_riesgo_sin_evidencia" if baja else "bajo_riesgo_documentado"


_TEXTO_EJE = {"riesgo": ("riesgo", "riesgosa"), "relevancia": ("relevancia", "relevante"), "incertidumbre": ("incertidumbre", "incierta")}


def _lectura(p: PuntoPareto, eje_y: str = "riesgo") -> str:
    n, adj = _TEXTO_EJE[eje_y]
    base = {"critico": f"Alta {n} con poca evidencia: prioridad máxima para obtener datos.",
            "alto_riesgo_documentado": f"Alta {n} pero ya documentada: sirve para validar el modelo.",
            "bajo_riesgo_sin_evidencia": f"Baja {n} y poca evidencia: seguimiento, no urgente.",
            "bajo_riesgo_documentado": f"Baja {n} y documentada: baja prioridad."}[p.cuadrante]
    if p.en_frontera:
        base += f" Está en la frontera de Pareto: ninguna otra investigación es a la vez más {adj} y peor documentada."
    if p.extrapolacion_combustible:
        base += " El modelo se calibró con combustibles sólidos: su riesgo aquí es una extrapolación."
    if p.inferidos:
        base += f" Posición con campos inferidos ({', '.join(p.inferidos)}): el riesgo se muestra con su intervalo."
    return base


def construir_pareto(predictor: PredictorIgnis, entorno: str = "luna", motor: str | None = None, eje_y: str = "riesgo") -> RespuestaPareto:
    """Calcula el análisis completo para el catálogo vigente (el riesgo se evalúa en un único lote vectorizado).

    Raises:
        KeyError: entorno desconocido.
    """
    if entorno not in ENTORNOS:
        raise KeyError(entorno)
    if eje_y not in EJES_Y:
        raise KeyError(eje_y)
    catalogo, estado = cargar_catalogo_con_estado()
    nuevas_ids = set(estado.nuevas_ingestadas)
    planes = [_plan_riesgo(i, entorno) for i in catalogo]
    lote: list[CondicionesAmbiente] = []
    for pl in planes:  # 1 centro + rejilla 5×5 uniforme sobre la caja de incertidumbre (O₂ × presión)
        o2c, pc, fl = pl["centro"]
        (o2a, o2b), (pa, pb) = pl["caja_o2"], pl["caja_p"]
        lote += [_condiciones(o2c, pc, fl), *(_condiciones(float(o), float(p), fl) for o in np.linspace(o2a, o2b, N_REJ) for p in np.linspace(pa, pb, N_REJ))]
    indices = [r.indice_riesgo for r in predictor.evaluar_lote(lote, motor=motor)]
    entorno_obj = ENTORNOS[entorno]
    puntos: list[PuntoPareto] = []
    muestras: list[np.ndarray] = []
    for k, (inv, pl) in enumerate(zip(catalogo, planes)):
        bloque = indices[k * (1 + N_REJ**2):(k + 1) * (1 + N_REJ**2)]
        y = round(float(bloque[0]), 1)
        rejilla = np.array(bloque[1:], dtype=float)
        muestras.append(rejilla)
        p10, p90 = np.percentile(rejilla, [10, 90])
        y_bajo, y_alto = round(float(min(p10, y)), 1), round(float(max(p90, y)), 1)  # el punto central siempre cae dentro de su intervalo
        medio = round(float(rejilla.mean()), 1)
        x, det = _evidencia(inv)
        o2c, pc, fl = pl["centro"]
        relev = puntuar(inv, entorno_obj)[0]
        incert = round(y_alto - y_bajo, 1)
        y_plano = {"riesgo": y, "relevancia": relev, "incertidumbre": incert}[eje_y]
        if eje_y != "riesgo":  # el intervalo solo describe al riesgo; en otros ejes el punto es exacto
            y_bajo = y_alto = y_plano
        puntos.append(PuntoPareto(
            id=inv.id, nombre=inv.nombre, familia=inv.familia, x=x, y=y_plano, y_bajo=y_bajo, y_alto=y_alto, capa=1, en_frontera=False,
            cuadrante=_cuadrante(x, y_plano), prioridad=round(y_plano * (1 - x / 100), 1), relevancia=relev, riesgo=y, incertidumbre=incert, riesgo_medio=medio, p_frontera=0.0, dominados=0, provisional=inv.id in nuevas_ids,
            operacion={"o2_pct": round(o2c * 100, 2), "presion_kpa": round(pc, 2), "flujo_cm_s": round(fl, 1)},
            inferidos=pl["inferidos"], fuera_de_dominio=pl["fuera"], extrapolacion_combustible="solido" not in inv.combustible_tipos, evidencia_detalle=det, lectura=""))
    capas = capas_no_dominadas([(p.x, p.y) for p in puntos])
    for p, c in zip(puntos, capas):
        p.capa, p.en_frontera = c, c == 1
        p.lectura = _lectura(p, eje_y)
    # `muestras` sigue el orden del catálogo, igual que `puntos` antes de ordenar
    pf = _p_frontera([p.x for p in puntos], [m for m in muestras], [p.y for p in puntos], remuestrear=eje_y == "riesgo")
    for k, p in enumerate(puntos):
        p.p_frontera = round(float(pf[k]), 3)
        p.dominados = sum(_domina((p.x, p.y), (q.x, q.y)) for q in puntos if q is not p)
    puntos.sort(key=lambda p: (p.capa, -p.prioridad, -p.relevancia, p.id))
    frente = sorted((p for p in puntos if p.en_frontera), key=lambda p: (p.x, p.y))
    linea = _escalera(frente)
    codo = max(frente, key=lambda p: (p.prioridad, p.relevancia), default=None)
    return RespuestaPareto(
        titulo=NOMBRE_ANALISIS, estado=estado, entorno=entorno,
        ejes={"x": Ejes(id="evidencia", nombre="Cantidad de evidencia (0-100)", min=0, max=100, sentido="mayor = más datos verificados"),
              "y": Ejes(id=eje_y, nombre=EJES_Y[eje_y][0], min=0, max=100, sentido=EJES_Y[eje_y][1])},
        cortes={"evidencia": CORTE_EVIDENCIA, "y": CORTE_RIESGO}, eje_y=eje_y, puntos=puntos, frontera=[p.id for p in frente], linea_frontera=linea,
        codo=codo.id if codo else None, hipervolumen=hipervolumen([(p.x, p.y) for p in puntos]),
        metodologia=[
            f"Eje Y elegido: {eje_y}. «riesgo» = índice del modelo en el punto de operación (intervalo = percentiles 10-90 sobre una rejilla 5×5 de O₂ × presión dentro de lo que se desconoce); «relevancia» = puntaje del ranking para el entorno; «incertidumbre» = ancho de ese intervalo (riesgo por descubrir).",
            f"Eje X: evidencia verificable con pesos de diseño {PESOS_EVIDENCIA} (datos en PSI pesan más). Un campo desconocido aporta 0, nunca se inventa.",
            "Dominancia: A domina a B si y(A) ≥ y(B) y evidencia(A) ≤ evidencia(B) con una desigualdad estricta. Capa 1 = frontera; las capas siguientes salen de ordenar de forma no dominada el resto.",
            "Prioridad = y × (1 − evidencia/100): lo que sigue sin cubrirse. El «codo» es la investigación de la frontera con mayor prioridad.",
            "P(frontera): Monte Carlo (1000 sorteos, semilla fija) donde el riesgo de cada investigación se muestrea de su propia incertidumbre; mide cuán robusta es su posición crítica. «Dominados» = a cuántas supera.",
            "Hipervolumen: fracción del plano dominada por el conjunto; baja a medida que llegan datos reales (puntos hacia la derecha).",
        ],
        supuestos=[
            f"Campos de O₂/presión desconocidos se infieren del entorno objetivo ({entorno_obj.nombre}: {entorno_obj.o2_pct:g} % O₂, {entorno_obj.presion_kpa:g} kPa)"
            + (" — ese entorno es un supuesto" if entorno_obj.es_supuesto else "") + ".",
            f"Flujo desconocido = {FLUJO_DEFECTO_CM_S:g} cm/s (valor por defecto del Monitor); material y espesor fijos (sibal, 0,2 mm).",
            "El modelo es sintético, calibrado con anclas y NO validado; está entrenado en microgravedad y para combustibles sólidos: en gas, aerosol y gotas el riesgo es una extrapolación.",
            "«Verificado» significa declarado en el catálogo con su fuente; IGNIS no lo ha contrastado con la fuente primaria.",
            "Con los metadatos de PSI aún sin leer, casi todas las investigaciones comparten posición de riesgo (se infiere del entorno); por eso «relevancia» separa mejor hoy. Con datos reales el riesgo también se separará.",
        ],
        aviso="Priorización de experimentos con heurísticas de diseño explicables; no sustituye la validación por un especialista ni los datos oficiales de PSI.")


def _escalera(frente: list[PuntoPareto]) -> list[PuntoLinea]:
    """Polilínea en escalera de la frontera (evidencia creciente), lista para dibujar."""
    if not frente:
        return []
    pts: list[PuntoLinea] = [PuntoLinea(x=0.0, y=frente[0].y)]
    for p in frente:
        pts += [PuntoLinea(x=p.x, y=pts[-1].y), PuntoLinea(x=p.x, y=p.y)]
    pts.append(PuntoLinea(x=100.0, y=frente[-1].y))
    # elimina duplicados consecutivos
    limpio = [pts[0]]
    for q in pts[1:]:
        if (q.x, q.y) != (limpio[-1].x, limpio[-1].y):
            limpio.append(q)
    return limpio
