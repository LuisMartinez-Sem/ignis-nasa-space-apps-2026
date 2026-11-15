// @ts-check
/**
 * Análisis de Frontera de Pareto para priorización de experimentos (interactivo).
 * Consume GET /api/v1/investigaciones/pareto?entorno=&eje_y= . Los puntos se mueven solos cuando llegan datos nuevos.
 * Todo texto del servidor entra con textContent.
 */
import { etiqueta, etiquetarTexto } from "./etiquetas.js";
import { h, obtener } from "./dom.js";
import { observarTamano, prepararLienzo, reducirMovimiento, suavizar } from "./lienzo.js";

const COLOR = { capa1: "#ff3b3b", capa2: "#ff7a3c", capa3: "#ffb347", resto: "#7f91ab", cian: "#4fd1ff", texto: "#98a9c2" };
const EJES = /** @type {[string, string][]} */ ([["riesgo", "Riesgo"], ["relevancia", "Relevancia"], ["incertidumbre", "Incertidumbre"]]);
const MARGEN = { i: 50, d: 20, s: 16, b: 42 };

/**
 * Agrupa puntos con idéntica posición (muchas investigaciones comparten posición mientras PSI no entregue datos).
 * @param {{ id: string, nombre: string, x: number, y: number, capa: number, en_frontera: boolean }[]} puntos
 */
export function agrupar(puntos) {
  /** @type {Map<string, any>} */ const mapa = new Map();
  for (const p of puntos) {
    const k = `${p.x}|${p.y}`;
    const g = mapa.get(k) ?? { x: p.x, y: p.y, capa: p.capa, en_frontera: false, miembros: [] };
    g.miembros.push(p);
    g.en_frontera = g.en_frontera || p.en_frontera;
    g.capa = Math.min(g.capa, p.capa);
    mapa.set(k, g);
  }
  return [...mapa.values()];
}

/** Proyecta (evidencia, y) a píxeles. @param {number} W @param {number} H */
export function proyector(W, H) {
  const w = W - MARGEN.i - MARGEN.d, hh = H - MARGEN.s - MARGEN.b;
  return { mi: MARGEN.i, ms: MARGEN.s, w, hh, X: (/** @type {number} */ x) => MARGEN.i + (x / 100) * w, Y: (/** @type {number} */ y) => MARGEN.s + (1 - y / 100) * hh };
}

/** Texto accesible de un grupo de puntos. @param {any} g */
export function describirGrupo(g) {
  const nombres = g.miembros.map((/** @type {any} */ m) => m.nombre).join(", ");
  return `${nombres} — evidencia ${g.x}, valor ${g.y}${g.en_frontera ? " (frontera de Pareto)" : ` (capa ${g.capa})`}`;
}

/** Posición intermedia entre dos estados (para animar el movimiento de los puntos). @param {number} a @param {number} b @param {number} t */
export const mezclar = (a, b, t) => a + (b - a) * t;

/** Color de la capa de Pareto. @param {number} capa */
export const colorCapa = (capa) => (capa === 1 ? COLOR.capa1 : capa === 2 ? COLOR.capa2 : capa === 3 ? COLOR.capa3 : COLOR.resto);

/**
 * @param {{ lienzo: HTMLCanvasElement, barra: HTMLElement, resumen: HTMLElement, lista: HTMLElement, detalle: HTMLElement, aviso: HTMLElement,
 *   obtenerEntorno: () => string, alSeleccionar: (id: string, destino?: string) => void }} o
 */
export function crearPareto(o) {
  const { lienzo, barra, resumen, lista, detalle, aviso } = o;
  /** @type {any} */ let datos = null;
  /** @type {any[]} */ let grupos = [];
  /** @type {Map<string, {x:number,y:number}>} */ let mostrado = new Map();
  /** @type {Map<string, {x:number,y:number}>} */ let origen = new Map();
  let t0 = 0, raf = 0, eje = "riesgo", entornoUsado = "", seleccion = "", huellaVista = "";
  /** @type {any} */ let hover = null;
  /** @type {Map<string, any>} */ let porId = new Map();

  const pos = (/** @type {string} */ id, /** @type {any} */ p) => mostrado.get(id) ?? { x: p.x, y: p.y };

  /** Brillo mayor si el punto está seleccionado (solo presentación). @param {any} g */
  const sel0 = (g) => g.miembros.some((/** @type {any} */ q) => q.id === seleccion);

  function dibujar() {
    if (!datos) return;
    const { ctx, W, H } = prepararLienzo(lienzo);
    const { mi, ms, w, hh, X, Y } = proyector(W, H);
    ctx.clearRect(0, 0, W, H);
    // fondo con degradado radial (solo presentación)
    { const fondo = ctx.createRadialGradient(W * 0.2, H * 0.1, 10, W * 0.5, H * 0.5, Math.max(W, H) * 0.8); fondo.addColorStop(0, "rgba(255,59,59,0.10)"); fondo.addColorStop(0.55, "rgba(79,209,255,0.04)"); fondo.addColorStop(1, "rgba(4,8,15,0)"); ctx.fillStyle = fondo; ctx.fillRect(0, 0, W, H); }
    const cx = datos.cortes.evidencia, cy = datos.cortes.y;  // el servidor entrega `cortes.y` (antes `cortes.riesgo`)
    ctx.fillStyle = "rgba(255,59,59,0.09)"; ctx.fillRect(X(0), Y(100), X(cx) - X(0), Y(cy) - Y(100));
    ctx.fillStyle = "rgba(79,209,255,0.05)"; ctx.fillRect(X(cx), Y(100), X(100) - X(cx), Y(cy) - Y(100));
    ctx.strokeStyle = "rgba(152,169,194,0.16)"; ctx.lineWidth = 1; ctx.font = "11px 'JetBrains Mono', monospace"; ctx.fillStyle = COLOR.texto;
    for (const v of [0, 25, 50, 75, 100]) { ctx.beginPath(); ctx.moveTo(X(v), Y(0)); ctx.lineTo(X(v), Y(100)); ctx.moveTo(X(0), Y(v)); ctx.lineTo(X(100), Y(v)); ctx.stroke(); ctx.fillText(String(v), X(v) - 7, H - 24); ctx.fillText(String(v), 22, Y(v) + 4); }
    ctx.setLineDash([5, 4]); ctx.strokeStyle = "rgba(152,169,194,0.45)"; ctx.beginPath(); ctx.moveTo(X(cx), Y(100)); ctx.lineTo(X(cx), Y(0)); ctx.moveTo(X(0), Y(cy)); ctx.lineTo(X(100), Y(cy)); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillText("Evidencia → más datos verificados", mi + w / 2 - 105, H - 6);
    ctx.save(); ctx.translate(12, ms + hh / 2 + 55); ctx.rotate(-Math.PI / 2); ctx.fillText(`${datos.ejes.y.nombre.split(" (")[0]} →`, 0, 0); ctx.restore();
    ctx.fillStyle = "rgba(255,59,59,0.85)"; ctx.fillText("CRÍTICO: mucho en juego, poca evidencia", X(0) + 8, Y(100) + 14);
    // escalera de la frontera (con el mostrado actual no animado: el servidor ya la calcula)
    ctx.strokeStyle = COLOR.capa1; ctx.lineWidth = 2; ctx.shadowColor = COLOR.capa1; ctx.shadowBlur = 8; ctx.beginPath();
    datos.linea_frontera.forEach((/** @type {{x:number,y:number}} */ q, /** @type {number} */ i) => (i ? ctx.lineTo(X(q.x), Y(q.y)) : ctx.moveTo(X(q.x), Y(q.y))));
    ctx.stroke(); ctx.shadowBlur = 0;
    // incertidumbre P10-P90 (solo eje riesgo)
    if (eje === "riesgo") {
      ctx.strokeStyle = "rgba(79,209,255,0.30)"; ctx.lineWidth = 1.4;
      for (const g of grupos) { const m = g.miembros[0], p = pos(m.id, m); if (m.y_alto - m.y_bajo < 1) continue; ctx.beginPath(); ctx.moveTo(X(p.x), Y(m.y_bajo)); ctx.lineTo(X(p.x), Y(m.y_alto)); ctx.stroke(); for (const yy of [m.y_bajo, m.y_alto]) { ctx.beginPath(); ctx.moveTo(X(p.x) - 4, Y(yy)); ctx.lineTo(X(p.x) + 4, Y(yy)); ctx.stroke(); } }
    }
    // puntos: tamaño = relevancia; arco = probabilidad de estar en la frontera
    for (const g of grupos) {
      const m = g.miembros[0], p = pos(m.id, m), px = X(p.x), py = Y(p.y);
      const r = 5 + (Math.max(...g.miembros.map((/** @type {any} */ q) => q.relevancia)) / 100) * 6 + (g.miembros.length > 1 ? 2 : 0);
      g.px = px; g.py = py; g.r = r;
      ctx.beginPath(); ctx.arc(px, py, r, 0, 6.3); { const col = colorCapa(g.capa), gr = ctx.createRadialGradient(px - r * 0.3, py - r * 0.3, r * 0.1, px, py, r); gr.addColorStop(0, "#ffffff"); gr.addColorStop(0.35, col); gr.addColorStop(1, col); ctx.shadowColor = col; ctx.shadowBlur = sel0(g) ? 22 : 12; ctx.fillStyle = gr; ctx.fill(); ctx.shadowBlur = 0; }
      const pf = Math.max(...g.miembros.map((/** @type {any} */ q) => q.p_frontera));
      if (pf > 0 && pf < 1) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(px, py, r + 4, -Math.PI / 2, -Math.PI / 2 + 6.2832 * pf); ctx.stroke(); }
      const sel = g.miembros.some((/** @type {any} */ q) => q.id === seleccion), hov = g === hover;
      ctx.lineWidth = sel || hov ? 3 : 2; ctx.strokeStyle = sel ? "#ffffff" : hov ? "#4fd1ff" : "#0a0e17"; ctx.stroke();
      if (g.miembros.some((/** @type {any} */ q) => q.provisional)) { ctx.setLineDash([3, 2]); ctx.strokeStyle = "#ffb347"; ctx.beginPath(); ctx.arc(px, py, r + 7, 0, 6.3); ctx.stroke(); ctx.setLineDash([]); }
    }
    // etiquetas escalonadas
    let previo = -1e9, nivel = 0;
    ctx.font = "11px 'JetBrains Mono', monospace";
    for (const g of [...grupos].sort((a, b) => a.px - b.px)) {
      const txt = g.miembros.length <= 2 ? g.miembros.map((/** @type {any} */ m) => m.nombre).join(" · ") : `×${g.miembros.length}`;
      nivel = g.px - previo < 120 ? nivel + 1 : 0; previo = g.px;
      const dy = [-16, 20, -30, 34][nivel % 4], tw = ctx.measureText(txt).width, lx = g.x > 80 ? g.px - g.r - 6 - tw : g.px - tw / 2;
      ctx.fillStyle = "rgba(10,14,23,0.7)"; ctx.fillRect(lx - 3, g.py + dy - 11, tw + 6, 15); ctx.fillStyle = "#e6edf7"; ctx.fillText(txt, lx, g.py + dy);
    }
  }

  function animar(/** @type {number} */ ahora) {
    const k = Math.min(1, (ahora - t0) / 700), e = suavizar(k);
    for (const p of datos.puntos) { const a = origen.get(p.id) ?? { x: p.x, y: p.y }; mostrado.set(p.id, { x: mezclar(a.x, p.x, e), y: mezclar(a.y, p.y, e) }); }
    agruparMostrado();
    dibujar();
    raf = k < 1 ? requestAnimationFrame(animar) : 0;
  }
  /** Reagrupa por posición mostrada (durante la animación los puntos se separan solos). */
  function agruparMostrado() { grupos = agrupar(datos.puntos.map((/** @type {any} */ p) => ({ ...p, x: round(pos(p.id, p).x), y: round(pos(p.id, p).y), _real: p }))).map((g) => ({ ...g, miembros: g.miembros.map((/** @type {any} */ q) => q._real) })); }
  const round = (/** @type {number} */ v) => Math.round(v * 20) / 20;

  function pintarBarra() {
    barra.replaceChildren();
    const seg = h("div", "segmentos");
    seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "Eje vertical");
    for (const [id, nombre] of EJES) {
      const b = /** @type {HTMLButtonElement} */ (h("button", "segmento", nombre));
      b.type = "button"; b.setAttribute("aria-pressed", String(eje === id));
      b.addEventListener("click", () => { eje = id; cargar(true); });
      seg.append(b);
    }
    barra.append(h("span", "inv-etq", "Eje vertical"), seg);
  }

  function pintarResumen() {
    const codo = datos.puntos.find((/** @type {any} */ p) => p.id === datos.codo);
    const cifras = [["Frontera", `${datos.frontera.length} de ${datos.puntos.length}`, "Investigaciones que nadie supera a la vez en riesgo y en falta de evidencia"],
      ["Prioridad máxima", codo ? codo.nombre : "—", "El «codo»: la de la frontera con más riesgo aún sin cubrir"],
      ["Hipervolumen", `${(datos.hipervolumen * 100).toFixed(0)} %`, "Fracción del plano dominada por el conjunto; baja cuando llegan datos reales"]];
    const pills = cifras.map(([k, v, t]) => { const d = h("div", "pill"); d.title = t; d.append(h("span", "pill-k", k), h("strong", "pill-v mono", v)); return d; });
    const glosa = h("ul", "par-glosa");
    const hv = (datos.hipervolumen * 100).toFixed(0);
    for (const [k, t] of [
      ["Frontera", `${datos.frontera.length} investigación(es) que ninguna otra supera a la vez en riesgo y en falta de evidencia. No es «las peores»: es «las que más urge cubrir».`],
      ["Prioridad máxima", `${codo ? codo.nombre : "—"}: la de la frontera con mayor prioridad = riesgo × (1 − evidencia/100). Es la primera que habría que estudiar o completar.`],
      ["Hipervolumen " + hv + " %", `Qué parte del plano riesgo × evidencia queda «a la sombra» de las investigaciones: ${hv} % significa que todavía hay mucho riesgo sin respaldo de datos. Baja cuando llegan datos reales (los puntos se mueven a la derecha) o cuando se prueban condiciones de menor riesgo; no es un porcentaje de seguridad.`]]) {
      const li = h("li"); li.append(h("b", null, k + ": "), document.createTextNode(t)); glosa.append(li);
    }
    resumen.replaceChildren(h("div", "inv-herr"), glosa);
    resumen.firstChild?.append(...pills);
  }

  function pintarLista() {
    const ordenados = [...datos.puntos].sort((/** @type {any} */ a, /** @type {any} */ b) => b.prioridad - a.prioridad);
    lista.replaceChildren(...ordenados.map((/** @type {any} */ p, /** @type {number} */ i) => {
      const li = h("li", "par-fila"); li.dataset.capa = String(Math.min(p.capa, 4));
      const b = /** @type {HTMLButtonElement} */ (h("button", "par-boton"));
      b.type = "button"; b.setAttribute("aria-pressed", String(p.id === seleccion));
      const barra2 = h("span", "par-barra"); const rel = h("span"); rel.style.width = `${p.prioridad}%`; barra2.append(rel);
      b.append(h("span", "par-pos mono", String(i + 1)), h("strong", "par-nombre", p.nombre + (p.provisional ? "  · NUEVA" : "")), h("span", "par-val mono", p.prioridad.toFixed(0)), barra2,
        h("span", "par-sub", `${p.en_frontera ? "FRONTERA · " : `capa ${p.capa} · `}P(frontera) ${(p.p_frontera * 100).toFixed(0)} % · domina a ${p.dominados}`));
      b.addEventListener("click", () => seleccionar(p.id));
      // al pasar el cursor por la fila se resalta su punto en el gráfico
      const punto = () => grupos.find((g) => g.miembros.some((/** @type {any} */ q) => q.id === p.id)) ?? null;
      li.addEventListener("mouseenter", () => { hover = punto(); dibujar(); });
      li.addEventListener("mouseleave", () => { hover = null; dibujar(); });
      li.append(b); return li;
    }));
  }

  function pintarDetalle() {
    const p = porId.get(seleccion);
    if (!p) { detalle.replaceChildren(h("p", "inv-nota", "Toca un punto o una fila: verás por qué está donde está.")); return; }
    const barra2 = h("div", "evi-barra"); barra2.setAttribute("role", "img"); barra2.setAttribute("aria-label", `Evidencia ${p.x} de 100`);
    for (const c of p.evidencia_detalle) { const s = h("span", `evi-${c.estado}`); s.style.flexGrow = String(c.peso); s.title = `${etiqueta(c.campo)}: ${etiquetarTexto(c.motivo)} (${c.aporte}/${c.peso})`; barra2.append(s); }
    const ver = /** @type {HTMLButtonElement} */ (h("button", "boton", "Ver análisis completo")); ver.type = "button"; ver.addEventListener("click", () => o.alSeleccionar(p.id, "analisis"));
    const chips = h("div", "chips"); for (const f of p.inferidos) chips.append(h("span", "chip-inf", `${etiqueta(f)} inferido`));
    const grupo = grupos.find((g) => g.miembros.some((/** @type {any} */ q) => q.id === p.id));
    const hermanas = h("div", "par-grupo");
    if (grupo && grupo.miembros.length > 1) {
      hermanas.append(h("span", "inv-etq", `Comparten este punto (${grupo.miembros.length}) — elige una:`));
      for (const m of grupo.miembros) { const b = /** @type {HTMLButtonElement} */ (h("button", "chip-inv", m.nombre)); b.type = "button"; b.setAttribute("aria-pressed", String(m.id === seleccion)); b.addEventListener("click", () => seleccionar(m.id)); hermanas.append(b); }
      hermanas.append(h("p", "inv-nota", "Están juntas porque IGNIS las evalúa en la misma atmósfera objetivo mientras sus condiciones reales de O₂ y presión no estén verificadas."));
    }
    detalle.replaceChildren(h("h4", "par-titulo", p.nombre), h("p", "inv-nota", etiquetarTexto(p.lectura)), barra2, hermanas,
      h("p", "inv-nota", `Prioridad ${p.prioridad.toFixed(0)} = riesgo ${p.y.toFixed(0)} × (1 − evidencia ${p.x}/100). Evidencia ${p.x}/100: ${p.evidencia_detalle.map((/** @type {any} */ c) => `${etiqueta(c.campo)} ${c.estado}`).join(" · ")}`), chips,
      h("p", "inv-nota", `Riesgo ${p.riesgo.toFixed(0)} (P10-P90: ${p.y_bajo.toFixed(0)}-${p.y_alto.toFixed(0)}) · relevancia ${p.relevancia.toFixed(0)} · en la frontera el ${(p.p_frontera * 100).toFixed(0)} % de los sorteos`), ver);
  }

  /** @param {string} id */
  function seleccionar(id, notificar = true) {
    seleccion = id; pintarLista(); pintarDetalle(); dibujar();
    lista.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest" });
    if (notificar) o.alSeleccionar(id);
  }

  async function cargar(forzar = false) {
    const entorno = ["iss", "luna", "marte"].includes(o.obtenerEntorno()) ? o.obtenerEntorno() : "luna";
    try {
      const r = await fetch(`/api/v1/investigaciones/pareto?entorno=${entorno}&eje_y=${eje}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const nuevo = await r.json();
      const firma = JSON.stringify(nuevo.puntos.map((/** @type {any} */ p) => [p.id, p.x, p.y, p.p_frontera, p.capa]));
      if (!forzar && datos && firma === huellaVista && entorno === entornoUsado) return;
      origen = new Map(mostrado); datos = nuevo; huellaVista = firma; entornoUsado = entorno;
      porId = new Map(datos.puntos.map((/** @type {any} */ p) => [p.id, p]));
      if (!porId.has(seleccion)) seleccion = datos.codo ?? "";
      pintarBarra(); pintarResumen(); pintarLista(); pintarDetalle();
      aviso.textContent = `${datos.titulo}. ${datos.supuestos.join(" ")} ${datos.metodologia.join(" ")}`;
      lienzo.setAttribute("aria-label", `Dispersión de ${datos.puntos.length} investigaciones; ${datos.frontera.length} en la frontera de Pareto: ${datos.frontera.join(", ")}`);
      cancelAnimationFrame(raf); t0 = performance.now();
      if (reducirMovimiento() || origen.size === 0) { mostrado = new Map(datos.puntos.map((/** @type {any} */ p) => [p.id, { x: p.x, y: p.y }])); agruparMostrado(); dibujar(); }
      else raf = requestAnimationFrame(animar);
    } catch (error) {
      console.error("[IGNIS] pareto", error);
      aviso.textContent = "No se pudo cargar el análisis de Pareto (¿el modelo sigue cargando?).";
    }
  }

  lienzo.addEventListener("mousemove", (ev) => {
    const r = lienzo.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
    const g = grupos.find((q) => Math.hypot((q.px ?? -99) - x, (q.py ?? -99) - y) < (q.r ?? 8) + 5) ?? null;
    if (g !== hover) { hover = g; lienzo.style.cursor = g ? "pointer" : "default"; if (g) lienzo.title = describirGrupo(g); else lienzo.removeAttribute("title"); dibujar(); }
  });
  lienzo.addEventListener("mouseleave", () => { hover = null; dibujar(); });
  lienzo.addEventListener("click", () => {
    if (!hover) return;
    // en un grupo, cada clic recorre a sus miembros (posiciones idénticas)
    const ids = hover.miembros.map((/** @type {any} */ m) => m.id), k = ids.indexOf(seleccion);
    seleccionar(ids[(k + 1) % ids.length]);
  });
  lienzo.tabIndex = 0;
  lienzo.addEventListener("keydown", (ev) => {
    if (!datos || (ev.key !== "ArrowDown" && ev.key !== "ArrowUp")) return;
    ev.preventDefault();
    const ids = datos.puntos.map((/** @type {any} */ p) => p.id), k = ids.indexOf(seleccion);
    seleccionar(ids[(k + (ev.key === "ArrowDown" ? 1 : -1) + ids.length) % ids.length]);
  });
  const refrescar = observarTamano(lienzo, dibujar);

  return {
    cargar: () => cargar(false),
    recargarSiCambio: () => cargar(false),
    /** @param {string} id */
    resaltar(id) { if (porId.has(id)) { seleccion = id; if (datos) { pintarLista(); pintarDetalle(); dibujar(); } } },
    entornoCambio() { return cargar(true); },
    /** Redibuja al mostrar la pestaña: el canvas estuvo oculto y pudo conservar un tamaño viejo. */
    redibujar() { refrescar(); },
  };
}
