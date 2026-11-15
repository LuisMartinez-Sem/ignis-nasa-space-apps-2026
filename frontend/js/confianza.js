// @ts-check
/**
 * Informe de confianza: cuánto respaldo tiene el riesgo de una investigación (verificado / inferido / supuesto),
 * cómo se calcula el número y qué dato pedirle primero a PSI. Todo texto del servidor entra con textContent.
 */
import { etiquetarTexto } from "./etiquetas.js";
import { h, obtener } from "./dom.js";

const API = "/api/v1/investigaciones";
const ETIQUETA = { verificado: "Verificado", parcial: "Parcial", inferido: "Inferido", supuesto: "Supuesto" };

/** Reparte las entradas del modelo en porcentajes por estado. @param {Record<string, number>} resumen */
export function porcentajes(resumen) {
  const total = Object.values(resumen).reduce((a, b) => a + b, 0) || 1;
  return Object.fromEntries(Object.entries(resumen).map(([k, v]) => [k, Math.round((100 * v) / total)]));
}

/**
 * @param {{ entorno: () => string, nombres: () => { id: string, nombre: string }[] }} o
 */
export function crearConfianza(o) {
  const cont = obtener("inv-confianza");
  let actual = "";

  /** @param {string} id */
  async function pintar(id) {
    actual = id || actual;
    const nombres = o.nombres();
    if (!actual && nombres[0]) actual = nombres[0].id;
    const sel = /** @type {HTMLSelectElement} */ (h("select")); sel.setAttribute("aria-label", "Investigación");
    for (const n of nombres) { const op = h("option", null, n.nombre); op.value = n.id; op.selected = n.id === actual; sel.append(op); }
    sel.addEventListener("change", () => pintar(sel.value));
    const barra = h("div", "inv-herr"); barra.append(h("label", "inv-filtro", "Investigación "), sel);
    barra.firstElementChild?.append(sel);
    cont.replaceChildren(barra, h("p", "vacio", "Calculando…"));
    try {
      const r = await fetch(`${API}/${encodeURIComponent(actual)}/confianza?entorno=${encodeURIComponent(o.entorno())}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (d.id !== actual) return;
      cont.replaceChildren(barra, ...contenido(d));
    } catch (error) {
      console.error("[IGNIS] confianza", error);
      cont.replaceChildren(barra, h("p", "error", "No se pudo calcular el informe de confianza."));
    }
  }

  /** @param {any} d */
  function contenido(d) {
    const pct = porcentajes(d.resumen_entradas);
    const gauge = h("div", `conf-gauge conf-${d.nivel}`);
    gauge.append(h("strong", "conf-num mono", `${d.confianza.toFixed(0)}`), h("span", null, `/ 100 · confianza ${d.nivel}`));
    const producto = h("p", "inv-nota mono", `confianza = evidencia ${d.evidencia.toFixed(0)}${d.factores.map((/** @type {any} */ f) => ` × ${f.nombre.toLowerCase()} ${f.valor.toFixed(2)}`).join("")} = ${d.confianza.toFixed(1)}`);
    const lectura = h("p", "inv-interp", d.lectura);
    const rango = h("p", "inv-nota", `Índice de riesgo ${d.indice.toFixed(0)} (rango por lo desconocido: ${d.indice_p10.toFixed(0)}–${d.indice_p90.toFixed(0)}). Entorno: ${d.entorno}.`);
    const fac = h("ul", "conf-factores");
    for (const f of d.factores) { const li = h("li"); li.append(h("b", null, `${f.nombre} ${f.valor.toFixed(2)}`), document.createTextNode(` — ${etiquetarTexto(f.motivo)}`)); fac.append(li); }
    // Barra apilada: qué parte de las seis entradas está verificada, inferida o supuesta
    const apilada = h("div", "conf-apilada"); apilada.setAttribute("role", "img");
    apilada.setAttribute("aria-label", `Entradas del modelo: ${["verificado", "parcial", "inferido", "supuesto"].map((k) => `${pct[k] ?? 0} % ${k}`).join(", ")}`);
    for (const k of ["verificado", "parcial", "inferido", "supuesto"]) if (d.resumen_entradas[k]) { const s = h("span", `conf-${k}`, `${pct[k]} % ${ETIQUETA[/** @type {keyof typeof ETIQUETA} */ (k)].toLowerCase()}`); s.style.flexGrow = String(d.resumen_entradas[k]); apilada.append(s); }
    const tabla = h("table", "conf-tabla"); const cab = h("tr"); for (const t of ["Entrada", "Valor", "Estado", "De dónde sale"]) cab.append(h("th", null, t)); tabla.append(cab);
    for (const e of d.entradas) { const tr = h("tr"); const est = h("span", `conf-chip conf-${e.estado}`, ETIQUETA[/** @type {keyof typeof ETIQUETA} */ (e.estado)] ?? e.estado); const td = h("td"); td.append(est); tr.append(h("td", null, etiquetarTexto(e.variable)), h("td", "mono", e.valor), td, h("td", null, etiquetarTexto(e.origen))); tabla.append(tr); }
    const max = Math.max(1, ...d.sensibilidad.map((/** @type {any} */ s) => s.efecto_pts));
    const torn = h("ul", "conf-tornado");
    for (const s of d.sensibilidad) { const li = h("li"), b = h("span", "conf-tbarra"), rel = h("span", `conf-t-${s.estado}`); rel.style.width = `${(100 * s.efecto_pts) / max}%`; b.append(rel); li.append(h("span", null, `${etiquetarTexto(s.variable)} (${s.rango})`), b, h("span", "mono", `${s.efecto_pts.toFixed(1)} pts`)); torn.append(li); }
    const mejora = h("ul", "conf-mejora"); for (const m of d.como_mejorar) mejora.append(h("li", null, etiquetarTexto(m)));
    const pdf = /** @type {HTMLAnchorElement} */ (h("a", "boton", "Descargar informe (PDF)")); pdf.href = `${API}/${encodeURIComponent(d.id)}/confianza.pdf?entorno=${encodeURIComponent(d.entorno)}`; pdf.download = "";
    return [h("h3", "inv-titulo", d.nombre), gauge, lectura, producto, rango, fac,
      h("h4", "det-sec", "Qué parte del cálculo está respaldada"), apilada, tabla,
      h("h4", "det-sec", "Qué dato mueve más el índice (pídelo primero a PSI)"), torn, h("p", "inv-nota", d.pedir_primero),
      h("h4", "det-sec", "Cómo subir la confianza"), mejora, pdf, h("p", "inv-nota", d.aviso)];
  }

  return { pintar, actual: () => actual };
}
