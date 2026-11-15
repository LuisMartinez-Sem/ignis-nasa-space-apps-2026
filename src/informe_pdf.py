"""Informe forense ("caja negra") en PDF de un incidente simulado.

Solo resume lo que el simulador calculó o la cronología documentada: no inventa cifras. No estima vidas salvadas
(sería especulación); muestra la ventana de oportunidad contrafactual cuando existe. Los tiempos de supresión son
SIMULADOS (supuesto de escenario): IGNIS recomienda, no ejecuta la supresión.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pydantic import BaseModel, ConfigDict, Field

from src.emergencias import Emergencia
from src.simulador_incidentes import ComparativaIncidente

logger = logging.getLogger(__name__)

PIE = "Reporte generado automáticamente por IGNIS - Clasificación: Simulación"
ASPECTO_VIDAS = "IGNIS no estima vidas salvadas: sería especulación. Se reporta la ventana de oportunidad contrafactual."
FONDO, AMBAR, CIAN = colors.HexColor("#0a0e17"), colors.HexColor("#ffb347"), colors.HexColor("#4fd1ff")
GRIS, LINEA = colors.HexColor("#444444"), colors.HexColor("#c9ced6")
ANCHO_UTIL = A4[0] - 4 * cm
# Helvetica (WinAnsi) no tiene estos símbolos: se sustituyen para que no salgan como cuadros
_SUSTITUTOS = str.maketrans({"₂": "2", "→": "->", "≥": ">=", "≤": "<=", "≈": "~", "−": "-", "‑": "-", "·": "·", "Δ": "d", "•": "-"})


def _limpio(texto: object) -> str:
    return str(texto).translate(_SUSTITUTOS).encode("cp1252", "replace").decode("cp1252")


def _p(texto: object, estilo: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_limpio(texto)), estilo)


def _t(valor: float | None) -> str:
    return "n/d" if valor is None else f"{valor:.1f} s"


def _estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12)
    return {
        "n": normal,
        "c": ParagraphStyle("c", parent=normal, fontSize=8, leading=10, textColor=GRIS),
        "cab": ParagraphStyle("cab", parent=normal, fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, spaceBefore=12, spaceAfter=4,
                             textColor=colors.HexColor("#8a4f00")),
        "titulo": ParagraphStyle("t", parent=normal, fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#0a0e17")),
        "logo": ParagraphStyle("l", parent=normal, fontName="Helvetica-Bold", fontSize=30, leading=32, textColor=AMBAR),
        "sub": ParagraphStyle("s", parent=normal, fontSize=8, leading=10, textColor=CIAN),
        "der": ParagraphStyle("d", parent=normal, fontSize=8, leading=11, textColor=colors.white, alignment=2),
        "clave": ParagraphStyle("k", parent=normal, fontName="Helvetica-Bold"),
    }


def _encabezado(e: dict[str, ParagraphStyle], rotulo: str = "INFORME FORENSE") -> Table:
    """Bloque de marca: IGNIS en ámbar sobre fondo oscuro con franja cian."""
    t = Table([[[Paragraph("IGNIS", e["logo"]), Paragraph("Intelligent Guidance for Ignition &amp; Suppression", e["sub"])],
                [_p(rotulo, ParagraphStyle("x", parent=e["der"], fontName="Helvetica-Bold", fontSize=11, leading=14)),
                 _p(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", e["der"]), _p("Clasificación: SIMULACIÓN", e["der"])]]],
              colWidths=[ANCHO_UTIL * 0.6, ANCHO_UTIL * 0.4])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FONDO), ("LINEBELOW", (0, 0), (-1, -1), 3, CIAN),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    return t


def _tabla(e: dict[str, ParagraphStyle], cabecera: list[str], filas: list[list[Any]], anchos: list[float], zebra: bool = True) -> Table:
    datos = [[_p(c, e["cab"]) for c in cabecera]] + [[c if isinstance(c, Paragraph) else _p(c, e["n"]) for c in f] for f in filas]
    t = Table(datos, colWidths=anchos, repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), FONDO), ("GRID", (0, 0), (-1, -1), 0.3, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if zebra:
        estilo += [("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")])]
    t.setStyle(TableStyle(estilo))
    return t


def _pie(canvas: Canvas, doc: Any) -> None:
    """Pie de página común a todos los informes."""
    canvas.saveState()
    canvas.setStrokeColor(LINEA)
    canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(2 * cm, 1.05 * cm, _limpio(PIE))
    canvas.drawRightString(A4[0] - 2 * cm, 1.05 * cm, f"Página {doc.page}")
    canvas.restoreState()


def datos_clave(comparativa: ComparativaIncidente, emergencia: Emergencia | None = None) -> dict[str, Any]:
    """Cifras de la tabla resumen. Todo sale de la simulación; la supresión solo si hay un escenario que la defina."""
    m = comparativa.impacto.metricas
    deteccion = m.get("reaccion_ignis_s")
    if deteccion is None and emergencia is not None:
        deteccion = emergencia.mediciones.get("deteccion_s")
    supresion = next((ev.t_s for ev in emergencia.timeline_ignis if "supresión" in ev.accion.lower()), None) if emergencia else None
    referencia = m.get("ventana_min_s")
    tiempo_ignis = None if deteccion is None else float(deteccion) + (supresion or 0.0)
    ventaja = None if (referencia is None or tiempo_ignis is None or supresion is None) else round(float(referencia) - tiempo_ignis, 1)
    return {"deteccion_s": deteccion, "supresion_s": supresion, "referencia_humana_s": referencia, "ventaja_s": ventaja}


def _acciones(comparativa: ComparativaIncidente, emergencia: Emergencia | None) -> list[str]:
    if emergencia is not None:
        guia = [g for g in emergencia.guia_copiloto if not g.startswith("Apoyo a decisión")]
        if guia:
            return guia
    return [f"{ev.accion}: {ev.resultado}".rstrip(": ") for ev in comparativa.timeline_ignis if ev.categoria == "respuesta"]


def generar_informe_pdf(comparativa: ComparativaIncidente, emergencia: Emergencia | None = None) -> bytes:
    """Devuelve el PDF (bytes) del informe forense de una comparativa ya simulada.

    Args:
        comparativa: resultado de `SimuladorIncidentes.simular`.
        emergencia: ficha de Modo Emergencia equivalente (aporta supresión simulada y guía del copiloto), si existe.
    """
    e = _estilos()
    k = datos_clave(comparativa, emergencia)

    pie = _pie
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=2.2 * cm,
                            title=_limpio(f"IGNIS - Informe forense - {comparativa.nombre}"), author="IGNIS")
    h: list = [_encabezado(e), Spacer(1, 12), _p(comparativa.nombre, e["titulo"]),
               _p(f"Tipo: {comparativa.tipo.value} · Duración simulada: {comparativa.duracion_s:.0f} s · Origen del modelo: {comparativa.origen_datos_modelo}", e["c"])]
    if comparativa.advertencia_modelo:
        h += [Spacer(1, 6), _tabla(e, ["Advertencia"], [[comparativa.advertencia_modelo]], [ANCHO_UTIL], zebra=False)]

    h.append(_p("Resumen de respuesta", e["h2"]))
    supresion_txt = _t(k["supresion_s"]) + (" (SIMULADO: supuesto de escenario)" if k["supresion_s"] is not None else " (IGNIS recomienda; no ejecuta supresión)")
    ventaja_txt = "n/d" if k["ventaja_s"] is None else f"{k['ventaja_s']:.1f} s = {k['referencia_humana_s']:.0f} s (fin del fuego, humano) - ({_t(k['deteccion_s'])} + {_t(k['supresion_s'])})"
    acciones = _acciones(comparativa, emergencia)
    h.append(_tabla(e, ["Indicador", "Valor"], [
        ["Tiempo de detección de IGNIS", _t(k["deteccion_s"]) + (" (medido por el detector TCN)" if k["deteccion_s"] is not None else "")],
        ["Tiempo de supresión", supresion_txt],
        ["Ventaja de IGNIS (calculada, contrafactual)", ventaja_txt],
        ["Acciones recomendadas por el copiloto", Paragraph("<br/>".join(escape(_limpio(f"{i}. {a}")) for i, a in enumerate(acciones, 1)) or "n/d", e["n"])],
    ], [5.5 * cm, ANCHO_UTIL - 5.5 * cm]))
    h.append(_p("La ventaja es una ventana de oportunidad contrafactual, no un resultado medido.", e["c"]))

    for titulo, eventos in (("Cronología humana (documentada)", comparativa.timeline_humano),
                            ("Reacción de IGNIS (calculada por los modelos)", comparativa.timeline_ignis)):
        filas = [[_t(ev.t_s), ev.accion, ev.resultado, ev.confianza] for ev in eventos] or [["n/d", "Sin eventos", "", ""]]
        h.append(KeepTogether([_p(titulo, e["h2"]), _tabla(e, ["t", "Acción", "Resultado", "Confianza"], filas,
                                                            [1.6 * cm, 6.2 * cm, 6.2 * cm, ANCHO_UTIL - 14 * cm])]))

    h.append(_p("Impacto estimado (contrafactual)", e["h2"]))
    h.append(_p(comparativa.impacto.titulo + ": " + comparativa.impacto.resumen, e["n"]))
    h += [_p(f"- {kk}: {v if v is not None else 'n/d'}", e["n"]) for kk, v in comparativa.impacto.metricas.items()]
    h += [Spacer(1, 4), _p(ASPECTO_VIDAS, e["n"]), _p("Metodología: " + comparativa.impacto.metodologia, e["c"]),
          _p("Supuestos y límites", e["h2"]), *[_p("- " + s, e["n"]) for s in comparativa.supuestos],
          _p("Fuentes", e["h2"]), *[_p("- " + str(f.model_dump().get("titulo") or f.model_dump()), e["c"]) for f in comparativa.fuentes],
          Spacer(1, 8), _p("Apoyo a decisión. No sustituye los procedimientos de misión.", e["c"])]
    doc.build(h, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()


# --------------------------------------------------------------------------- simulación en vivo
class PuntoHistorial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_s: float = Field(..., ge=0, le=1e6)
    indice_riesgo: float = Field(..., ge=0, le=100)


class EstadoVivo(BaseModel):
    """Estado actual del simulador enviado por el HUD. Es lo que el HUD REPORTA: el servidor no lo re-verifica."""

    model_config = ConfigDict(extra="forbid")

    escenario: str = Field("Monitor en vivo", max_length=80)
    t_s: float | None = Field(None, ge=0, le=1e6)
    indice_riesgo: float | None = Field(None, ge=0, le=100)
    nivel_riesgo: str | None = Field(None, max_length=20)
    velocidad_propagacion_mm_s: float | None = Field(None, ge=0, le=1000)
    probabilidad_propagacion: float | None = Field(None, ge=0, le=1)
    probabilidad_llama_fria: float | None = Field(None, ge=0, le=1)
    estado_llama_fria: str | None = Field(None, max_length=30)
    alarma_detector: bool = False
    evento_activo: bool = False
    fuera_de_dominio: bool = False
    condiciones: dict[str, float | str | None] = Field(default_factory=dict, max_length=20)
    acciones_sugeridas: list[str] = Field(default_factory=list, max_length=20)
    advertencias: list[str] = Field(default_factory=list, max_length=20)
    historial: list[PuntoHistorial] = Field(default_factory=list, max_length=600)


_NOMBRES_CONDICION = {"fraccion_o2": "O2 (fracción)", "velocidad_flujo_cm_s": "Flujo (cm/s)", "presion_kpa": "Presión (kPa)",
                      "temperatura_ambiente_k": "T ambiente (K)", "espesor_combustible_mm": "Espesor combustible (mm)",
                      "material": "Material", "regimen_flujo": "Régimen de flujo", "temperatura_reaccion_k": "T de reacción (K)"}


def _fmt(v: Any, nd: int = 2, sufijo: str = "") -> str:
    if v is None:
        return "n/d"
    return f"{v:.{nd}f}{sufijo}" if isinstance(v, float) else f"{v}{sufijo}"


def _grafica_historial(historial: list[PuntoHistorial]) -> Drawing:
    """Índice de riesgo vs tiempo (0-100) como polilínea simple."""
    ancho, alto, mi, mb = ANCHO_UTIL, 110.0, 30.0, 18.0
    d = Drawing(ancho, alto)
    d.add(Line(mi, mb, ancho - 6, mb, strokeColor=GRIS, strokeWidth=0.6))
    d.add(Line(mi, mb, mi, alto - 6, strokeColor=GRIS, strokeWidth=0.6))
    for nivel in (25, 50, 75):
        y = mb + (alto - mb - 6) * nivel / 100
        d.add(Line(mi, y, ancho - 6, y, strokeColor=LINEA, strokeWidth=0.3))
        d.add(String(4, y - 3, str(nivel), fontName="Helvetica", fontSize=6.5, fillColor=GRIS))
    t0, t1 = historial[0].t_s, historial[-1].t_s
    span = (t1 - t0) or 1.0
    pts: list[float] = []
    for pt in historial:
        pts += [mi + (ancho - mi - 6) * (pt.t_s - t0) / span, mb + (alto - mb - 6) * pt.indice_riesgo / 100]
    if len(historial) >= 2:
        d.add(PolyLine(pts, strokeColor=colors.HexColor("#d98200"), strokeWidth=1.4))
    d.add(String(mi, 4, f"t = {t0:.0f} s", fontName="Helvetica", fontSize=6.5, fillColor=GRIS))
    d.add(String(ancho - 50, 4, f"t = {t1:.0f} s", fontName="Helvetica", fontSize=6.5, fillColor=GRIS))
    return d


def generar_informe_vivo_pdf(estado: EstadoVivo) -> bytes:
    """PDF 'Caja Negra' del estado actual del simulador, con el mismo formato del informe forense."""
    e = _estilos()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.5 * cm, bottomMargin=2.2 * cm,
                            title=_limpio(f"IGNIS - Caja negra - {estado.escenario}"), author="IGNIS")
    clasificacion = "Potencial latente (sin evento)" if not estado.evento_activo else "EVENTO ACTIVO"
    h: list = [_encabezado(e, "CAJA NEGRA · EN VIVO"), Spacer(1, 12), _p(estado.escenario, e["titulo"]),
               _p(f"Instante del simulador: {_fmt(estado.t_s, 1, ' s')} · Estado: {clasificacion}", e["c"]),
               Spacer(1, 6), _tabla(e, ["Aviso"], [["Estado reportado por el HUD en el momento de la descarga; el servidor no lo re-verifica. "
                                                     "Cifras de modelo sintético calibrado con anclas publicadas (ajuste, no validación)."]],
                                    [ANCHO_UTIL], zebra=False),
               _p("Estado actual", e["h2"])]
    nivel = f"{_fmt(estado.indice_riesgo, 0)} / 100" + (f" ({estado.nivel_riesgo})" if estado.nivel_riesgo else "")
    if estado.fuera_de_dominio:
        nivel += " · FUERA DE DOMINIO (extrapolación)"
    h.append(_tabla(e, ["Indicador", "Valor"], [
        ["Índice de riesgo", nivel],
        ["Velocidad de propagación", _fmt(estado.velocidad_propagacion_mm_s, 2, " mm/s")],
        ["Probabilidad de propagación", _fmt(None if estado.probabilidad_propagacion is None else estado.probabilidad_propagacion * 100, 0, " %")],
        ["Llama fría", f"{_fmt(None if estado.probabilidad_llama_fria is None else estado.probabilidad_llama_fria * 100, 0, ' %')} · {estado.estado_llama_fria or 'n/d'}"],
        ["Alarma del detector temporal (TCN)", "ACTIVA" if estado.alarma_detector else "Sin alarma"],
        ["Evento", clasificacion],
    ], [6 * cm, ANCHO_UTIL - 6 * cm]))
    if estado.condiciones:
        filas = [[_NOMBRES_CONDICION.get(k, k), _fmt(v, 3 if k == "fraccion_o2" else 2)] for k, v in estado.condiciones.items()]
        h += [_p("Condiciones del módulo", e["h2"]), _tabla(e, ["Variable", "Valor"], filas, [6 * cm, ANCHO_UTIL - 6 * cm])]
    acciones = Paragraph("<br/>".join(escape(_limpio(f"{i}. {a}")) for i, a in enumerate(estado.acciones_sugeridas, 1)) or "n/d", e["n"])
    h += [_p("Acciones recomendadas por el copiloto", e["h2"]), _tabla(e, ["Acciones"], [[acciones]], [ANCHO_UTIL], zebra=False)]
    if estado.advertencias:
        h += [_p("Advertencias del modelo", e["h2"]), *[_p("- " + a, e["n"]) for a in estado.advertencias]]
    if len(estado.historial) >= 2:
        picos = max(estado.historial, key=lambda p: p.indice_riesgo)
        h += [KeepTogether([_p("Historial del índice de riesgo", e["h2"]), _grafica_historial(estado.historial),
                            _p(f"{len(estado.historial)} muestras · máximo {picos.indice_riesgo:.0f} en t = {picos.t_s:.0f} s.", e["c"])])]
    h += [Spacer(1, 8), _p(ASPECTO_VIDAS, e["c"]), _p("Apoyo a decisión. No sustituye los procedimientos de misión.", e["c"])]
    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue()
