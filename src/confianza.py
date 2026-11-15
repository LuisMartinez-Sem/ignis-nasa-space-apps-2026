"""Informe de confianza: cuánto se puede creer el riesgo que IGNIS asigna a una investigación, y por qué.

Un ranking o un índice de riesgo sin su grado de respaldo invita a confiar de más. Este módulo separa, para cada
investigación y entorno objetivo, lo que está **verificado** (declarado con fuente en el catálogo), lo **inferido** (tomado del
entorno objetivo) y lo **supuesto** (valores por defecto del modelo), y lo convierte en un número auditable:

    confianza = evidencia × f_combustible × f_gravedad × f_validación            (0-100)

* ``evidencia`` (0-100) es la misma del eje X del Pareto: pesos de diseño O₂ 25, presión 20, flujo 10, datos en PSI 30, gravedad 15.
* ``f_combustible``: el modelo se entrenó con **sólidos**; en gas, gota o aerosol el riesgo es una extrapolación.
* ``f_gravedad``: el modelo se calibró en **microgravedad**; en gravedad parcial no hay datos en PSI.
* ``f_validación``: tope fijo mientras el modelo no se contraste con datos independientes (hoy: no lo está).

Además mide, con el propio modelo, **cuánto mueve el índice cada variable desconocida** (análisis tornado): eso dice qué dato
pedirle primero a PSI. Todos los factores son heurísticas de diseño explicables, no una probabilidad calibrada.
"""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from src.investigaciones import ENTORNOS, Investigacion
from src.pareto import FLUJO_DEFECTO_CM_S, _condiciones, _evidencia, _plan_riesgo
from src.predictor import PredictorIgnis

FACTOR_VALIDACION = 0.85  # tope mientras no exista validación independiente (docs/validacion_externa.md)
FLUJO_RANGO_CM_S = (0.0, 50.0)  # rango explorado cuando el flujo de las pruebas se desconoce
PUNTOS_TORNADO = 9
NIVELES = ((60.0, "alta"), (30.0, "media"), (0.0, "baja"))

Estado = Literal["verificado", "parcial", "inferido", "supuesto"]


class EntradaModelo(BaseModel):
    """Una de las seis entradas del modelo de riesgo y de dónde sale su valor."""

    variable: str
    valor: str
    estado: Estado
    origen: str


class FactorConfianza(BaseModel):
    nombre: str
    valor: float = Field(..., ge=0, le=1)
    motivo: str


class EfectoVariable(BaseModel):
    """Cuánto cambia el índice al recorrer la variable en su rango plausible (resto fijo en el punto de operación)."""

    variable: str
    estado: Literal["verificado", "inferido"]
    rango: str
    efecto_pts: float
    indice_min: float
    indice_max: float


class InformeConfianza(BaseModel):
    id: str
    nombre: str
    entorno: str
    indice: float
    indice_p10: float
    indice_p90: float
    evidencia: float
    factores: list[FactorConfianza]
    confianza: float = Field(..., ge=0, le=100)
    nivel: Literal["alta", "media", "baja"]
    entradas: list[EntradaModelo]
    resumen_entradas: dict[str, int]
    sensibilidad: list[EfectoVariable]
    pedir_primero: str
    como_mejorar: list[str]
    lectura: str
    aviso: str


def _nivel(c: float) -> Literal["alta", "media", "baja"]:
    return next(n for corte, n in NIVELES if c >= corte)  # type: ignore[return-value]


def _factor_combustible(inv: Investigacion) -> FactorConfianza:
    tipos = set(inv.combustible_tipos)
    if tipos == {"solido"}:
        return FactorConfianza(nombre="Combustible", valor=1.0, motivo="sólido: el tipo con el que se entrenó el modelo")
    if "solido" in tipos:
        return FactorConfianza(nombre="Combustible", valor=0.7, motivo=f"mezcla sólido + {', '.join(sorted(tipos - {'solido'}))}: solo la parte sólida está cubierta")
    return FactorConfianza(nombre="Combustible", valor=0.4, motivo=f"{', '.join(sorted(tipos)) or 'sin clasificar'}: el riesgo es una extrapolación del modelo de sólidos")


def _factor_gravedad(inv: Investigacion) -> FactorConfianza:
    tabla = {
        "microgravedad": (1.0, "microgravedad: el régimen en que se calibró el modelo"),
        "parcial_emulada": (0.6, "gravedad parcial solo emulada con campos eléctricos"),
        "parcial_pendiente": (0.4, "gravedad parcial: PSI aún no tiene datos, el resultado acota con micro y 1 g"),
        "desconocida": (0.4, "régimen de gravedad no declarado"),
    }
    v, m = tabla[inv.gravedad]
    return FactorConfianza(nombre="Gravedad", valor=v, motivo=m)


def _entradas(inv: Investigacion, plan: dict) -> list[EntradaModelo]:
    o2, p, f = inv.o2_pct, inv.presion_kpa, inv.flujo_cm_s
    centro_o2, centro_p, centro_f = plan["centro"]
    def estado(conocido_total: bool, conocido_parcial: bool) -> Estado:
        return "verificado" if conocido_total else "parcial" if conocido_parcial else "inferido"
    return [
        EntradaModelo(variable="O₂", valor=f"{centro_o2 * 100:.1f} %", origen="declarado en el catálogo (con fuente)" if o2.min is not None and o2.max is not None else "tomado del entorno objetivo",
                      estado=estado(o2.min is not None and o2.max is not None, o2.min is not None or o2.max is not None)),
        EntradaModelo(variable="Presión", valor=f"{centro_p:.1f} kPa", origen="declarada en el catálogo" if p and p.min is not None and p.max is not None else "tomada del entorno objetivo",
                      estado=estado(bool(p and p.min is not None and p.max is not None), bool(p and (p.min is not None or p.max is not None)))),
        EntradaModelo(variable="Flujo de aire", valor=f"{centro_f:.0f} cm/s", origen="declarado en el catálogo" if f and f.min is not None and f.max is not None else "valor por defecto del Monitor",
                      estado="verificado" if f and f.min is not None and f.max is not None else "inferido"),
        EntradaModelo(variable="Material", valor="SIBAL", estado="supuesto", origen="referencia de Saffire; el catálogo no detalla el material por prueba"),
        EntradaModelo(variable="Espesor", valor="0,2 mm", estado="supuesto", origen="valor de referencia del modelo"),
        EntradaModelo(variable="T ambiente", valor="295 K", estado="supuesto", origen="valor de referencia del modelo"),
    ]


def _tornado(predictor: PredictorIgnis, plan: dict) -> list[EfectoVariable]:
    """Recorre cada variable en su rango plausible (resto en el punto de operación) y mide el efecto sobre el índice."""
    o2c, pc, fc = plan["centro"]
    sets = {
        "O₂": (plan["caja_o2"], lambda v: _condiciones(float(v), pc, fc), "o2_pct" not in plan["inferidos"], lambda lo, hi: f"{lo * 100:.0f}-{hi * 100:.0f} %"),
        "Presión": (plan["caja_p"], lambda v: _condiciones(o2c, float(v), fc), "presion_kpa" not in plan["inferidos"], lambda lo, hi: f"{lo:.0f}-{hi:.0f} kPa"),
        "Flujo de aire": (FLUJO_RANGO_CM_S, lambda v: _condiciones(o2c, pc, float(v)), "flujo_cm_s" not in plan["inferidos"], lambda lo, hi: f"{lo:.0f}-{hi:.0f} cm/s"),
    }
    salida: list[EfectoVariable] = []
    for nombre, ((lo, hi), construir, conocido, formato) in sets.items():
        if conocido and nombre == "Flujo de aire":
            continue  # el flujo declarado no se explora: es un valor puntual del experimento
        indices = [r.indice_riesgo for r in predictor.evaluar_lote([construir(v) for v in np.linspace(lo, hi, PUNTOS_TORNADO)])]
        salida.append(EfectoVariable(variable=nombre, estado="verificado" if conocido else "inferido", rango=formato(lo, hi),
                                     efecto_pts=round(max(indices) - min(indices), 1), indice_min=round(min(indices), 1), indice_max=round(max(indices), 1)))
    return sorted(salida, key=lambda e: -e.efecto_pts)


def construir_informe(predictor: PredictorIgnis, inv: Investigacion, entorno: str = "luna") -> InformeConfianza:
    """Calcula el informe de confianza de una investigación.

    Raises:
        KeyError: entorno desconocido.
    """
    if entorno not in ENTORNOS:
        raise KeyError(entorno)
    plan = _plan_riesgo(inv, entorno)
    x, det = _evidencia(inv)
    o2c, pc, fc = plan["centro"]
    (o2a, o2b), (pa, pb) = plan["caja_o2"], plan["caja_p"]
    lote = [_condiciones(o2c, pc, fc), *(_condiciones(float(o), float(p), fc) for o in np.linspace(o2a, o2b, 5) for p in np.linspace(pa, pb, 5))]
    idx = np.array([r.indice_riesgo for r in predictor.evaluar_lote(lote)])
    indice, rejilla = float(idx[0]), idx[1:]
    p10, p90 = (float(v) for v in np.percentile(rejilla, [10, 90]))
    factores = [_factor_combustible(inv), _factor_gravedad(inv),
                FactorConfianza(nombre="Validación", valor=FACTOR_VALIDACION, motivo="el modelo es sintético y calibrado con anclas; aún no se contrasta con datos independientes")]
    confianza = round(x * float(np.prod([f.valor for f in factores])), 1)
    entradas = _entradas(inv, plan)
    resumen = {k: sum(e.estado == k for e in entradas) for k in ("verificado", "parcial", "inferido", "supuesto")}
    sens = _tornado(predictor, plan)
    desconocidas = [s for s in sens if s.estado == "inferido"]
    pedir = (f"{desconocidas[0].variable}: recorrer {desconocidas[0].rango} mueve el índice {desconocidas[0].efecto_pts:.0f} puntos; es el dato que más reduce la incertidumbre."
             if desconocidas and desconocidas[0].efecto_pts >= 1 else "Ninguna variable desconocida mueve el índice más de 1 punto: la incertidumbre ya es pequeña.")
    mejoras = [f"Verificar «{d['campo']}»: {d['motivo']}" for d in (c.model_dump() for c in det) if d["estado"] != "verificado"]
    if factores[0].valor < 1:
        mejoras.append("Modelar este tipo de combustible con sus propios datos (hoy es una extrapolación del modelo de sólidos).")
    mejoras.append("Contrastar el modelo con datos independientes (NTRS/PSI) y revisión de un especialista: sube el tope de validación.")
    nivel = _nivel(confianza)
    lectura = (f"Confianza {nivel} ({confianza:.0f}/100): el índice {indice:.0f} puede ir de {p10:.0f} a {p90:.0f} por lo que no se conoce. "
               + ("Sirve para decidir con apoyo del equipo." if nivel == "alta" else "Úsalo para priorizar qué estudiar, no para decidir." if nivel == "media" else "Es un orden de magnitud: no lo uses como cifra."))
    return InformeConfianza(
        id=inv.id, nombre=inv.nombre, entorno=entorno, indice=round(indice, 1), indice_p10=round(min(p10, indice), 1), indice_p90=round(max(p90, indice), 1), evidencia=x,
        factores=factores, confianza=confianza, nivel=nivel, entradas=entradas, resumen_entradas=resumen, sensibilidad=sens, pedir_primero=pedir, como_mejorar=mejoras, lectura=lectura,
        aviso="Heurística de diseño explicable; no es una probabilidad calibrada ni sustituye la validación por un especialista ni los datos oficiales de PSI.")


def informe_pdf(inf: InformeConfianza) -> bytes:
    """PDF de una página con el informe (reportlab)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    est = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=est["BodyText"], fontSize=9.5, leading=13)
    titulo = ParagraphStyle("t", parent=est["Title"], fontSize=18, leading=22, alignment=0)
    h2 = ParagraphStyle("h2", parent=est["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.6 * cm, title=f"Informe de confianza — {inf.nombre}", author="IGNIS")
    def tabla(filas: list[list[str]], anchos: list[float]) -> Table:
        t = Table(filas, colWidths=anchos, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b2638")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7b8")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t
    p = lambda s: Paragraph(s.replace("&", "&amp;").replace("<", "&lt;"), normal)  # noqa: E731
    producto = " × ".join([f"{inf.evidencia:.0f}"] + [f"{f.valor:.2f}" for f in inf.factores])
    hist = [Paragraph(f"Informe de confianza: {inf.nombre.replace('&', '&amp;')}", titulo), p(f"Entorno objetivo: {ENTORNOS[inf.entorno].nombre}. IGNIS — Intelligent Guidance for Ignition & Suppression."), Spacer(1, 6),
            Paragraph(f"Confianza {inf.nivel.upper()}: {inf.confianza:.0f} / 100", h2), p(inf.lectura), p(f"Cálculo: evidencia × combustible × gravedad × validación = {producto} = {inf.confianza:.1f}"),
            Paragraph("Factores del modelo", h2), tabla([["Factor", "Valor", "Motivo"]] + [[f.nombre, f"{f.valor:.2f}", Paragraph(f.motivo.replace("&", "&amp;"), normal)] for f in inf.factores], [3 * cm, 2 * cm, 12 * cm]),
            Paragraph("Entradas del modelo: verificado, inferido o supuesto", h2),
            tabla([["Variable", "Valor", "Estado", "Origen"]] + [[e.variable, e.valor, e.estado, Paragraph(e.origen.replace("&", "&amp;"), normal)] for e in inf.entradas], [3 * cm, 2.6 * cm, 2.4 * cm, 9 * cm]),
            Paragraph("Qué mueve el índice (análisis tornado)", h2),
            tabla([["Variable", "Estado", "Rango", "Efecto (pts)"]] + [[s.variable, s.estado, s.rango, f"{s.efecto_pts:.1f}  ({s.indice_min:.0f}–{s.indice_max:.0f})"] for s in inf.sensibilidad], [4 * cm, 3 * cm, 4 * cm, 6 * cm]),
            Spacer(1, 4), p("Dato a pedir primero: " + inf.pedir_primero), Paragraph("Cómo subir la confianza", h2), *[p("• " + m) for m in inf.como_mejorar], Spacer(1, 8), p(inf.aviso)]
    doc.build(hist)
    return buf.getvalue()
