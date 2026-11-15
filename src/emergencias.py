"""Modo Emergencia enriquecido: 4 escenarios con cronología humana, reacción de IGNIS, impacto y guía.

Principios de honestidad (heredados de `incidentes_historicos`):
  - Los tiempos de IGNIS se MIDEN corriendo el detector TCN y el predictor sobre la telemetría del
    guion; nunca se escriben a mano. Los valores objetivo de diseño van aparte (`objetivos_diseno`).
  - Cada hecho lleva su confianza: documentado | aproximado | medido_modelo | supuesto | hipotetico.
  - `tiempo_ahorrado_s` es una VENTANA DE OPORTUNIDAD contrafactual (referencia humana − reacción de
    IGNIS), nunca una medición de "N veces más rápido".
  - IGNIS NO localiza el foco en 3D con los sensores actuales: la localización se declara no implementada.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from src.detector_temporal import UMBRAL_REPOSO
from src.escenarios import (
    Escenario, Fuego, Marca, Reproduccion, _con, _interp, _rampa, catalogo_escenarios, generar_reproduccion, trazar_detector,
)
from src.predictor import PredictorIgnis

logger = logging.getLogger(__name__)

Confianza = Literal["documentado", "aproximado", "medido_modelo", "supuesto", "hipotetico"]
IDS_EMERGENCIAS = ("mir-1997", "iss-2015", "columbus-cool-flame", "saffire-cable")
DESCARGO = "Apoyo a decisión. No sustituye los procedimientos de misión."


class ErrorEmergencia(ValueError):
    """Emergencia desconocida o sin componente imprescindible (detector)."""


class EventoEmergencia(BaseModel):
    t_s: float | None
    accion: str
    resultado: str = ""
    confianza: Confianza


class ImpactoEmergencia(BaseModel):
    tiempo_ahorrado_s: float | None  # ventana de oportunidad contrafactual; None si no está definida
    tipo_tiempo: str
    vidas_en_riesgo: int | None
    modulo_afectado: str
    nota: str = ""


class Emergencia(BaseModel):
    id: str
    nombre: str
    es_hipotetico: bool
    condiciones_iniciales: dict[str, Any]
    timeline_humano: list[EventoEmergencia]
    timeline_ignis: list[EventoEmergencia]
    impacto: ImpactoEmergencia
    guia_copiloto: list[str]
    objetivos_diseno: dict[str, float] = Field(default_factory=dict)  # lo que se PIDIÓ; no es una medición
    mediciones: dict[str, float | None] = Field(default_factory=dict)  # lo que el modelo midió
    capacidades_no_implementadas: list[str] = Field(default_factory=list)
    advertencias: list[str] = Field(default_factory=list)
    inicio_evento_s: float = 0.0
    muestras: list[dict[str, Any]] = Field(default_factory=list)  # telemetría a 1 Hz para el HUD
    acciones_modelo: list[dict[str, Any]] = Field(default_factory=list)  # acciones sugeridas con primer instante


def _escenario_columbus() -> Escenario:
    """Llama fría pura (sin llama caliente previa) en el laboratorio Columbus, aire de la ISS. ILUSTRATIVO."""
    tr = _interp([(0, 296), (10, 296), (13, 690), (60, 690)])
    return Escenario("columbus-cool-flame", "Llama fría invisible en Columbus", "Llama fría en un panel del laboratorio Columbus.", 60,
                     "hipotetico", "Escenario hipotético: no hay un incidente real documentado.",
                     lambda t: _con(temperatura_reaccion_k=tr(t)), lambda t: (t * 0, 0.7 * _rampa(t, 10, 1.5)),
                     fuego=Fuego(sector="Columbus-P3", x_m=0.6, y_m=1.1))


def _escenario_cable() -> Escenario:
    """Incendio de aislante de cable (PMMA como proxy) en un módulo tipo Cygnus/Saffire. HIPOTÉTICO."""
    tr = _interp([(0, 296), (10, 296), (13, 900), (60, 950)])
    return Escenario("saffire-cable", "Incendio en cableado", "Aislante de cable en llamas.", 60, "hipotetico",
                     "Escenario hipotético: ningún experimento Saffire fue un incendio de cableado; PMMA es un proxy del aislante.",
                     lambda t: _con(material="pmma", espesor_combustible_mm=1.0, velocidad_flujo_cm_s=8.0, temperatura_reaccion_k=tr(t)),
                     lambda t: (0.8 * _rampa(t, 10, 1.2), t * 0), fuego=Fuego(sector="C-4", x_m=0.9, y_m=0.4))


def _primer_alarma_s(pasos: list[Any]) -> float | None:
    return next((round(p.t_s, 2) for p in pasos if p.alarma_nueva), None)


def _primer_s(repro: Reproduccion, predicado) -> float | None:
    return next((f.t_s for f in repro.frames if predicado(f)), None)


def construir_emergencia(identificador: str, predictor: PredictorIgnis, detector: Any) -> Emergencia:
    """Evalúa una emergencia con los modelos y devuelve su ficha completa.

    Args:
        identificador: uno de `IDS_EMERGENCIAS`.
        predictor: predictor con un motor entrenado.
        detector: `DetectorTemporal` (obligatorio: los tiempos de IGNIS salen de él).

    Raises:
        ErrorEmergencia: id desconocido o detector ausente.
    """
    if identificador not in IDS_EMERGENCIAS:
        raise ErrorEmergencia(f"Emergencia desconocida: {identificador!r}. Válidas: {IDS_EMERGENCIAS}")
    if detector is None:
        raise ErrorEmergencia("Se requiere el detector temporal: los tiempos de IGNIS se miden, no se escriben")
    base = {**catalogo_escenarios(), "columbus-cool-flame": _escenario_columbus(), "saffire-cable": _escenario_cable()}
    escenario = base[identificador]
    repro = generar_reproduccion(escenario, predictor, detector)
    pasos = trazar_detector(escenario, detector)
    alarma = _primer_alarma_s(pasos)
    condiciones = dict(repro.frames[0].condiciones)
    constructor = {"mir-1997": _mir, "iss-2015": _iss, "columbus-cool-flame": _columbus, "saffire-cable": _cable}[identificador]
    ficha = constructor(escenario, repro, pasos, alarma, condiciones)
    ficha.inicio_evento_s = 0.0 if identificador == "mir-1997" else 10.0
    ficha.muestras = [{"t_s": f.t_s, "indice_riesgo": f.indice_riesgo, "fraccion_o2": f.condiciones.get("fraccion_o2"),
                       "temperatura_reaccion_k": f.condiciones.get("temperatura_reaccion_k"), "nivel_riesgo": f.nivel_riesgo,
                       "estado_ntc": f.estado_llama_fria} for f in repro.frames]
    vistas: dict[str, float] = {}
    for f in repro.frames:
        if f.evento_activo:
            for a in f.acciones_sugeridas:
                vistas.setdefault(a, f.t_s)
    ficha.acciones_modelo = [{"descripcion": a, "primer_t_s": t} for a, t in vistas.items()]
    return ficha


def _mir(esc: Escenario, repro: Reproduccion, pasos: list[Any], alarma: float | None, cond: dict) -> Emergencia:
    t0 = 0.0  # el fuego empieza en t=0 según la ficha del incidente
    ignis = None if alarma is None else round(alarma - t0, 2)
    guia = _guia_desde_modelo(repro)
    return Emergencia(
        id=esc.id, nombre="Incendio en Mir (Kvant-1, SFOG)", es_hipotetico=False, condiciones_iniciales=cond,
        timeline_humano=[
            EventoEmergencia(t_s=0, accion="Se enciende el SFOG: llama de ~0,9 m con chispas y metal fundido", confianza="documentado"),
            EventoEmergencia(t_s=0, accion="La tripulación detecta el fuego visualmente de inmediato", resultado="La llama era evidente.", confianza="documentado"),
            EventoEmergencia(t_s=None, accion="Extintores de ESPUMA (no CO₂: el CO₂ es del segmento estadounidense de la ISS); la llama bloquea el acceso a una cápsula Soyuz", confianza="documentado"),
            EventoEmergencia(t_s=90, accion="Extinción: el fuego duró 90 s", resultado="Referencia de extinción para la comparación con IGNIS.", confianza="documentado"),
        ],
        timeline_ignis=[
            EventoEmergencia(t_s=ignis, accion="El detector TCN confirma el evento (3 votos consecutivos)", confianza="medido_modelo"),
            *_eventos_modelo(repro),
            EventoEmergencia(t_s=3.0, accion="Extinción simulada: supresión automática activada tras la detección (0,9 s)", resultado="Escenario SIMULADO; IGNIS no controla supresión real.", confianza="supuesto"),
        ],
        impacto=ImpactoEmergencia(
            tiempo_ahorrado_s=None if ignis is None else round(90 - ignis, 2), tipo_tiempo="ventana_de_oportunidad_contrafactual",
            vidas_en_riesgo=6, modulo_afectado="Kvant-1 (Mir)",
            nota="Detección de IGNIS (medida) frente al tiempo de extinción de 90 s. La tripulación ya veía la llama en t=0: IGNIS no detecta antes, aporta guía estructurada durante los 90 s. Ventana contrafactual, no ahorro medido."),
        guia_copiloto=["Aislar sector y usar espuma.", "Avisar a toda la tripulación; no usar CO₂ (extintor del segmento estadounidense de la ISS).", *[g for g in guia if "CO₂" not in g and "CO2" not in g],
                       "Verificar el acceso a ambas cápsulas de evacuación antes de combatir el fuego (en Mir una quedó bloqueada).",
                       "Preparar máscaras y extintores; el humo redujo la visibilidad 5–20 min (documentado).", DESCARGO],
        objetivos_diseno={"deteccion_s": 0.7, "extincion_s": 90.0, "extincion_ignis_simulada_s": 3.0}, mediciones={"deteccion_s": ignis, "extincion_s": 90.0},
        capacidades_no_implementadas=["Localización 3D del foco"],
        advertencias=["Telemetría ILUSTRATIVA construida por IGNIS desde la descripción cualitativa; no es una medición de Mir."])


def _iss(esc: Escenario, repro: Reproduccion, pasos: list[Any], alarma: float | None, cond: dict) -> Emergencia:
    inicio = 10.0  # pico sintético de un solo sensor
    despues = [p for p in pasos if p.t_s >= inicio]
    activo = [p for p in despues[:50] if (1.0 - p.probabilidades.get("NOMINAL", 1.0)) >= UMBRAL_REPOSO]
    descarte = 0.1 if not activo else round(activo[-1].t_s - inicio + 0.1, 2)
    falso_negativo = alarma is not None
    return Emergencia(
        id=esc.id, nombre="ISS 2015: falsa alarma de amoníaco", es_hipotetico=False, condiciones_iniciales=cond,
        timeline_humano=[
            EventoEmergencia(t_s=0, accion="La telemetría indica una posible fuga de amoníaco en el Nodo 2 (03:58 CST)", confianza="documentado"),
            EventoEmergencia(t_s=None, accion="La tripulación se refugia en el segmento ruso y se apagan equipos del Nodo 2/3, JEM y Columbus", confianza="documentado"),
            EventoEmergencia(t_s=None, accion="Causa raíz: indicación errónea del multiplexor Node 2-2 MDM", confianza="documentado"),
            EventoEmergencia(t_s=36480, accion="Reingreso con máscaras (~10 h después); no se encontró amoníaco", confianza="aproximado"),
        ],
        timeline_ignis=[
            EventoEmergencia(t_s=inicio, accion="Pico aislado en UN sensor (traza sintética análoga)", confianza="supuesto"),
            EventoEmergencia(t_s=round(inicio + descarte, 2), accion="El detector clasifica el pico como NO evento", resultado=f"Sin alarma en toda la traza: {'NO' if not falso_negativo else 'SÍ HUBO'} falsa alarma.", confianza="medido_modelo"),
        ],
        impacto=ImpactoEmergencia(
            tiempo_ahorrado_s=None if falso_negativo else 36480 - descarte, tipo_tiempo="ventana_de_oportunidad_contrafactual",
            vidas_en_riesgo=None, modulo_afectado="Nodo 2 (segmento estadounidense, ISS)",
            nota="Contrafactual: IGNIS no ejecuta ni decide evacuaciones; solo muestra que un pico aislado no basta para una alarma de fuego. El evento real fue de amoníaco (fuera del alcance de IGNIS). Nº de tripulantes no documentado en las fuentes del catálogo."),
        guia_copiloto=["Un solo sensor anómalo sin consenso multicanal: tratar como posible falla de instrumentación.",
                       "Contrastar con los otros canales (IR, luz visible, O₂, presión, CO) antes de evacuar.",
                       "Si el consenso persiste ≥ 0,3 s, escalar como evento real.", DESCARGO],
        objetivos_diseno={"descarte_s": 1.2}, mediciones={"descarte_s": descarte, "alarmas": 0.0 if not falso_negativo else 1.0},
        capacidades_no_implementadas=["Detección de amoníaco (fuera del alcance de IGNIS)"],
        advertencias=["La traza es SINTÉTICA; no hay datos de la ISS."])


def _columbus(esc: Escenario, repro: Reproduccion, pasos: list[Any], alarma: float | None, cond: dict) -> Emergencia:
    t0 = 10.0
    deteccion = None if alarma is None else round(alarma - t0, 2)
    alerta_abs = _primer_s(repro, lambda f: f.evento_activo and f.estado_llama_fria in ("POSIBLE", "PROBABLE"))
    alerta = None if alerta_abs is None else round(max(alerta_abs, alarma or 0.0) - t0, 2)
    return Emergencia(
        id=esc.id, nombre="Llama fría invisible en Columbus", es_hipotetico=True, condiciones_iniciales=cond,
        timeline_humano=[
            EventoEmergencia(t_s=None, accion="Sin detección visual: la llama fría no emite luz visible", resultado="Una cámara convencional no la ve (en pruebas sintéticas, solo el 2 % de las veces).", confianza="aproximado"),
            EventoEmergencia(t_s=None, accion="Puede reavivarse tras parecer extinguida", confianza="aproximado"),
        ],
        timeline_ignis=[
            EventoEmergencia(t_s=deteccion, accion="El detector TCN detecta la firma térmica/IR", confianza="medido_modelo"),
            EventoEmergencia(t_s=alerta, accion="Alerta de llama fría con temperatura de reacción", resultado="Estado POSIBLE/PROBABLE del módulo de Cool Flame (resolución 1 s).", confianza="medido_modelo"),
        ],
        impacto=ImpactoEmergencia(tiempo_ahorrado_s=None, tipo_tiempo="no_definido", vidas_en_riesgo=None, modulo_afectado="Columbus (ISS), ilustrativo",
                                  nota="Sin referencia humana: la detección visual no ocurre, así que no hay tiempo que restar. Escenario hipotético; sin tripulantes documentados."),
        guia_copiloto=["Confirmar con termografía IR antes de dar el sector por seguro.", "No dar por extinguido hasta que la T de reacción baje de 550 K.",
                       "Vigilar el sector: puede reavivarse en < 5 min.", "Aislar el panel afectado y mantener la ventilación controlada.", DESCARGO],
        objetivos_diseno={"deteccion_s": 0.7, "alerta_s": 2.0}, mediciones={"deteccion_s": deteccion, "alerta_s": alerta},
        capacidades_no_implementadas=["Localización 3D del foco"],
        advertencias=["Escenario hipotético; entradas ilustrativas, resultados calculados por los modelos."])


def _cable(esc: Escenario, repro: Reproduccion, pasos: list[Any], alarma: float | None, cond: dict) -> Emergencia:
    t0 = 10.0
    deteccion = None if alarma is None else round(alarma - t0, 2)
    guia_abs = _primer_s(repro, lambda f: f.evento_activo and f.nivel_riesgo in ("ALERTA", "CRITICO") and bool(f.acciones_sugeridas))
    guia_s = None if guia_abs is None else round(guia_abs - t0, 2)
    return Emergencia(
        id=esc.id, nombre="Incendio en cableado", es_hipotetico=True, condiciones_iniciales=cond,
        timeline_humano=[
            EventoEmergencia(t_s=45, accion="Localizar el foco recorriendo el módulo (45 s)", resultado="Tiempo aportado como supuesto de escenario; no es un dato documentado.", confianza="supuesto"),
        ],
        timeline_ignis=[
            EventoEmergencia(t_s=deteccion, accion="El detector TCN confirma el evento", confianza="medido_modelo"),
            EventoEmergencia(t_s=guia_s, accion="Hay guía de acciones sugeridas (nivel ALERTA o superior)", resultado="Resolución 1 s.", confianza="medido_modelo"),
            EventoEmergencia(t_s=None, accion="Localización 3D del foco: NO disponible con los sensores actuales", resultado="Requiere sensores distribuidos y un modelo de posición que IGNIS no tiene.", confianza="documentado"),
        ],
        impacto=ImpactoEmergencia(
            tiempo_ahorrado_s=None if deteccion is None else round(45 - deteccion, 2), tipo_tiempo="ventana_de_oportunidad_contrafactual_supuesto",
            vidas_en_riesgo=None, modulo_afectado="Módulo tipo Cygnus/Saffire, sector C-4 (hipotético)",
            nota="Compara una detección medida con un tiempo humano SUPUESTO; solo detección, no localización. Ningún experimento Saffire fue un incendio de cableado."),
        guia_copiloto=["Cortar la alimentación del circuito sospechoso si el procedimiento lo permite.", *_guia_desde_modelo(repro),
                       "Inspeccionar el sector con termografía IR para localizar el foco (IGNIS no localiza).", DESCARGO],
        objetivos_diseno={"localizacion_3d_s": 1.5, "guia_extincion_s": 3.0},
        mediciones={"deteccion_s": deteccion, "guia_s": guia_s, "localizacion_3d_s": None},
        capacidades_no_implementadas=["Localización 3D del foco"],
        advertencias=["PMMA es un proxy del aislante del cable; escenario hipotético."])


def _guia_desde_modelo(repro: Reproduccion) -> list[str]:
    """Acciones sugeridas por el predictor en el instante de mayor índice (sin duplicados)."""
    activos = [f for f in repro.frames if f.evento_activo and f.indice_riesgo is not None]
    if not activos:
        return []
    mejor = max(activos, key=lambda f: f.indice_riesgo or 0.0)
    return list(dict.fromkeys(mejor.acciones_sugeridas))


def _eventos_modelo(repro: Reproduccion) -> list[EventoEmergencia]:
    return [EventoEmergencia(t_s=m.t_s, accion=m.texto, confianza="medido_modelo") for m in repro.marcas_ignis if "TCN" not in m.texto]


def listar_emergencias() -> list[dict[str, str]]:
    """Catálogo mínimo (id y nombre) de las emergencias disponibles."""
    nombres = {"mir-1997": "Incendio en Mir (Kvant-1, SFOG)", "iss-2015": "ISS 2015: falsa alarma de amoníaco",
               "columbus-cool-flame": "Llama fría invisible en Columbus", "saffire-cable": "Incendio en cableado"}
    return [{"id": i, "nombre": nombres[i]} for i in IDS_EMERGENCIAS]
