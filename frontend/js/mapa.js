// @ts-check
/**
 * Mapa de riesgo atmosférico interactivo: índice del modelo sobre O₂ × presión, con entornos, cobertura experimental de las
 * investigaciones (se actualiza sola al ingerir datos), anclas de calibración y una sonda que evalúa el modelo real.
 * Consume GET /api/v1/mapa-riesgo y POST /api/v1/predict. Todo texto del servidor entra con textContent.
 */
import { h, obtener } from "./dom.js";
import { observarTamano, prepararLienzo, reducirMovimiento } from "./lienzo.js";

/** Paradas de color: coinciden con los niveles del HUD (25/50/75). */
const PARADAS = /** @type {[number, [number, number, number]][]} */ ([[0, [14, 28, 58]], [25, [79, 209, 255]], [50, [255, 179, 71]], [75, [255, 122, 60]], [100, [255, 59, 59]]]);
const NOMBRE_NIVEL = ["NOMINAL", "PRECAUCIÓN", "ALERTA", "CRÍTICO"];
const MARGEN = { i: 50, d: 18, s: 14, b: 40 };

/** Color [r,g,b] del índice 0-100 por interpolación lineal entre paradas. @param {number} v */
export function colorIndice(v) {
  const x = Math.min(100, Math.max(0, v));
  for (let k = 1; k < PARADAS.length; k++) {
    const [v1, c1] = PARADAS[k];
    if (x <= v1) {
      const [v0, c0] = PARADAS[k - 1], t = (x - v0) / (v1 - v0);
      return /** @type {[number, number, number]} */ (c0.map((c, i) => Math.round(c + (c1[i] - c) * t)));
    }
  }
  return PARADAS[PARADAS.length - 1][1];
}

/** Nombre del nivel (umbrales 25/50/75 del backend). @param {number} v */
export const nombreNivel = (v) => NOMBRE_NIVEL[v >= 75 ? 3 : v >= 50 ? 2 : v >= 25 ? 1 : 0];

/**
 * Índice interpolado bilinealmente sobre la rejilla del servidor (eje O₂ en columnas, presión en filas).
 * @param {{ o2_pct: number[], presion_kpa: number[], indice: number[][] }} m @param {number} o2 @param {number} p
 */
export function valorEn(m, o2, p) {
  const ejes = (/** @type {number[]} */ a, /** @type {number} */ x) => {
    const c = Math.min(a[a.length - 1], Math.max(a[0], x));
    let i = 0;
    while (i < a.length - 2 && c > a[i + 1]) i++;
    return [i, (c - a[i]) / (a[i + 1] - a[i])];
  };
  const [j, tj] = ejes(m.o2_pct, o2), [i, ti] = ejes(m.presion_kpa, p);
  const f = m.indice;
  return f[i][j] * (1 - ti) * (1 - tj) + f[i][j + 1] * (1 - ti) * tj + f[i + 1][j] * ti * (1 - tj) + f[i + 1][j + 1] * ti * tj;
}

/**
 * @param {{ lienzo: HTMLCanvasElement, lectura: HTMLElement, sonda: HTMLElement, leyenda: HTMLElement, capas: HTMLElement,
 *   alCargarEnMonitor?: (m: { modo: string, sliders: Record<string, number|boolean> }) => void, alSeleccionar?: (id: string) => void }} o
 */
export function crearMapa(o) {
  const { lienzo, lectura, sonda, leyenda, capas } = o;
  /** @type {any} */ let m = null;
  /** @type {HTMLCanvasElement|null} */ let fondo = null;
  const visibles = { entornos: true, cobertura: true, calibracion: true, tierra: true };
  /** @type {{ o2: number, p: number }|null} */ let cursor = null;
  /** @type {{ o2: number, p: number, res?: any }|null} */ let punto = null;
  /** @type {Set<string>} */ let vistas = new Set();
  /** @type {Map<string, number>} */ const nuevas = new Map();
  let activo = false, raf = 0;
  /** @type {any[]} */ let zonas = [];

  const geo = (/** @type {number} */ W, /** @type {number} */ H) => {
    const w = W - MARGEN.i - MARGEN.d, hh = H - MARGEN.s - MARGEN.b;
    const o2a = m.o2_pct[0], o2b = m.o2_pct.at(-1), pa = m.presion_kpa[0], pb = m.presion_kpa.at(-1);
    return { w, hh, X: (/** @type {number} */ v) => MARGEN.i + ((v - o2a) / (o2b - o2a)) * w, Y: (/** @type {number} */ v) => MARGEN.s + (1 - (v - pa) / (pb - pa)) * hh,
      inv: (/** @type {number} */ px, /** @type {number} */ py) => ({ o2: o2a + ((px - MARGEN.i) / w) * (o2b - o2a), p: pa + (1 - (py - MARGEN.s) / hh) * (pb - pa) }), o2a, o2b, pa, pb };
  };

  /** Imagen suave del campo (bilinear) en baja resolución; el navegador la escala con suavizado. */
  function construirFondo() {
    const NX = 200, NY = 120;
    fondo = document.createElement("canvas");
    fondo.width = NX; fondo.height = NY;
    const c = /** @type {CanvasRenderingContext2D} */ (fondo.getContext("2d"));
    const img = c.createImageData(NX, NY);
    const o2a = m.o2_pct[0], o2b = m.o2_pct.at(-1), pa = m.presion_kpa[0], pb = m.presion_kpa.at(-1);
    for (let y = 0; y < NY; y++) for (let x = 0; x < NX; x++) {
      const [r, g, b] = colorIndice(valorEn(m, o2a + (x / (NX - 1)) * (o2b - o2a), pb - (y / (NY - 1)) * (pb - pa)));
      img.data.set([r, g, b, 255], (y * NX + x) * 4);
    }
    c.putImageData(img, 0, 0);
  }

  /** @param {number} t */
  function dibujar(t = 0) {
    if (!m || !fondo) return;
    const { ctx, W, H } = prepararLienzo(lienzo);
    const g = geo(W, H);
    ctx.clearRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
    ctx.drawImage(fondo, MARGEN.i, MARGEN.s, g.w, g.hh);
    ctx.font = "11px 'JetBrains Mono', monospace";
    // ejes y rejilla tenue
    ctx.fillStyle = "#98a9c2"; ctx.strokeStyle = "rgba(255,255,255,0.10)"; ctx.lineWidth = 1;
    for (const v of [16, 20, 25, 30, 35, 40]) { ctx.beginPath(); ctx.moveTo(g.X(v), MARGEN.s); ctx.lineTo(g.X(v), MARGEN.s + g.hh); ctx.stroke(); ctx.fillText(String(v), g.X(v) - 7, H - 22); }
    for (const v of [40, 55, 70, 85, 100]) { ctx.beginPath(); ctx.moveTo(MARGEN.i, g.Y(v)); ctx.lineTo(MARGEN.i + g.w, g.Y(v)); ctx.stroke(); ctx.fillText(String(v), 14, g.Y(v) + 4); }
    ctx.fillText("O₂ (% en volumen)", MARGEN.i + g.w / 2 - 55, H - 6);
    ctx.save(); ctx.translate(12, MARGEN.s + g.hh / 2 + 45); ctx.rotate(-Math.PI / 2); ctx.fillText("Presión (kPa)", 0, 0); ctx.restore();
    zonas = [];
    // isolínea de la misma pO₂ que en la Tierra
    if (visibles.tierra) {
      ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.setLineDash([6, 5]); ctx.lineWidth = 1.5; ctx.beginPath();
      let primero = true;
      for (let p = g.pa; p <= g.pb; p += 0.5) { const o2 = (m.ppo2_tierra_kpa / p) * 100; if (o2 < g.o2a || o2 > g.o2b) continue; if (primero) { ctx.moveTo(g.X(o2), g.Y(p)); primero = false; } else ctx.lineTo(g.X(o2), g.Y(p)); }
      ctx.stroke(); ctx.setLineDash([]);
    }
    // cobertura experimental: regiones O₂ × presión conocidas de cada investigación
    if (visibles.cobertura) for (const c of m.cobertura ?? []) {
      const x0 = g.X(Math.max(g.o2a, c.o2_pct[0])), x1 = g.X(Math.min(g.o2b, c.o2_pct[1])), y0 = g.Y(Math.min(g.pb, c.presion_kpa[1])), y1 = g.Y(Math.max(g.pa, c.presion_kpa[0]));
      const nueva = nuevas.has(c.id) ? Math.max(0, 1 - (t - (nuevas.get(c.id) ?? 0)) / 2500) : 0;
      ctx.lineWidth = 2; ctx.strokeStyle = c.provisional ? "#ffb347" : "#ffffff";
      if (c.puntual || (x1 - x0 < 8 && y1 - y0 < 8)) {
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
        ctx.fillStyle = "#0a0e17"; ctx.fillRect(cx - 7, cy - 7, 14, 14); ctx.strokeRect(cx - 7, cy - 7, 14, 14);
        ctx.fillStyle = "#4fd1ff"; ctx.fillRect(cx - 4, cy - 4, 8, 8);
        if (nueva) { ctx.strokeStyle = `rgba(79,209,255,${nueva})`; ctx.beginPath(); ctx.arc(cx, cy, 10 + (1 - nueva) * 22, 0, 6.3); ctx.stroke(); }
        zonas.push({ tipo: "cobertura", id: c.id, x: cx, y: cy, r: 12, texto: `${c.nombre}: ${c.o2_pct[0]} % O₂, ${c.presion_kpa[0]} kPa` });
        etiqueta(ctx, c.nombre, cx + 12, cy - 10 + (c.id.length % 3) * 12);
      } else {
        ctx.fillStyle = "rgba(79,209,255,0.18)"; ctx.fillRect(x0, y0, x1 - x0, y1 - y0); ctx.setLineDash([5, 3]); ctx.strokeStyle = "#4fd1ff"; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0); ctx.setLineDash([]);
        zonas.push({ tipo: "cobertura", id: c.id, x: (x0 + x1) / 2, y: (y0 + y1) / 2, r: Math.max(12, (x1 - x0) / 2), texto: `${c.nombre}: ${c.o2_pct[0]}-${c.o2_pct[1]} % O₂, ${c.presion_kpa[0]}-${c.presion_kpa[1]} kPa` });
        etiqueta(ctx, c.nombre, x0 + 4, y0 + 13);
      }
    }
    // anclas de calibración (rombos)
    if (visibles.calibracion) for (const k of m.marcadores.filter((/** @type {any} */ q) => q.tipo === "evidencia" && q.dentro_del_dominio)) {
      const x = g.X(k.o2_pct), y = g.Y(k.presion_kpa);
      ctx.save(); ctx.translate(x, y); ctx.rotate(Math.PI / 4); ctx.strokeStyle = "#ffb347"; ctx.lineWidth = 2; ctx.strokeRect(-5, -5, 10, 10); ctx.restore();
      zonas.push({ tipo: "ancla", id: k.id, x, y, r: 10, texto: `Ancla de calibración: ${k.nombre} (${k.o2_pct} % O₂, ${k.presion_kpa} kPa)` });
    }
    // entornos con anillo que late (si el usuario no pidió menos movimiento)
    if (visibles.entornos) {
      const apilados = /** @type {{x:number,y:number}[]} */ ([]);
      for (const k of m.marcadores.filter((/** @type {any} */ q) => q.tipo === "entorno" && q.dentro_del_dominio)) {
        const x = g.X(k.o2_pct), y = g.Y(k.presion_kpa), n = apilados.filter((q) => Math.hypot(q.x - x, q.y - y) < 16).length;
        apilados.push({ x, y });
        const f = reducirMovimiento() ? 0.5 : (Math.sin(t / 450 + x) + 1) / 2;
        ctx.strokeStyle = `rgba(255,255,255,${0.15 + 0.35 * (1 - f)})`; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y, 8 + f * 8, 0, 6.3); ctx.stroke();
        ctx.fillStyle = "#fff"; ctx.strokeStyle = "#0a0e17"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 6, 0, 6.3); ctx.fill(); ctx.stroke();
        etiqueta(ctx, k.id === "iss" ? "ISS" : k.id === "luna" ? "Luna" : k.id === "marte" ? "Marte" : k.nombre, x + 11, y + 4 + n * 14);
        zonas.push({ tipo: "entorno", id: k.id, x, y, r: 11, texto: `${k.nombre}: ${k.o2_pct} % O₂, ${k.presion_kpa} kPa` });
      }
    }
    // sonda del usuario y cursor
    if (cursor) { ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(g.X(cursor.o2), MARGEN.s); ctx.lineTo(g.X(cursor.o2), MARGEN.s + g.hh); ctx.moveTo(MARGEN.i, g.Y(cursor.p)); ctx.lineTo(MARGEN.i + g.w, g.Y(cursor.p)); ctx.stroke(); ctx.setLineDash([]); }
    if (punto) {
      const x = g.X(punto.o2), y = g.Y(punto.p);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 9, 0, 6.3); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - 14, y); ctx.lineTo(x - 5, y); ctx.moveTo(x + 5, y); ctx.lineTo(x + 14, y); ctx.moveTo(x, y - 14); ctx.lineTo(x, y - 5); ctx.moveTo(x, y + 5); ctx.lineTo(x, y + 14); ctx.stroke();
    }
  }

  /** Etiqueta con fondo para que se lea sobre cualquier color. */
  function etiqueta(/** @type {CanvasRenderingContext2D} */ ctx, /** @type {string} */ txt, /** @type {number} */ x, /** @type {number} */ y) {
    const w = ctx.measureText(txt).width;
    ctx.fillStyle = "rgba(10,14,23,0.72)"; ctx.fillRect(x - 3, y - 11, w + 6, 15);
    ctx.fillStyle = "#e6edf7"; ctx.fillText(txt, x, y);
  }

  function bucle(/** @type {number} */ t) {
    if (!activo) { raf = 0; return; }
    dibujar(t);
    raf = reducirMovimiento() && nuevas.size === 0 ? 0 : requestAnimationFrame(bucle);
  }
  const arrancar = () => { if (!raf) raf = requestAnimationFrame(bucle); };

  function pintarLeyenda() {
    leyenda.replaceChildren();
    const barra = h("div", "mapa-escala");
    barra.style.background = `linear-gradient(90deg, ${PARADAS.map(([v, c]) => `rgb(${c}) ${v}%`).join(",")})`;
    const marcas = h("div", "mapa-escala-marcas");
    for (const [v, n] of /** @type {[number, string][]} */ ([[12, "NOMINAL"], [37, "PRECAUCIÓN"], [62, "ALERTA"], [87, "CRÍTICO"]])) { const s = h("span", null, n); s.style.left = `${v}%`; marcas.append(s); }
    const items = [["●", "Entornos (ISS, Luna, Marte): dónde se vive"], ["▭", "Cobertura experimental: lo que cada investigación declara haber probado"], ["◆", "Ancla de calibración del modelo"], ["┄", "Misma pO₂ que en la Tierra (21,3 kPa)"]];
    leyenda.append(h("p", "inv-nota", "Índice de riesgo del modelo (0-100), por nivel"), barra, marcas, h("ul", "mapa-simbolos"));
    leyenda.querySelector("ul")?.append(...items.map(([s, t]) => { const li = h("li"); li.append(h("b", null, s), h("span", null, ` ${t}`)); return li; }));
    const fuera = m.marcadores.filter((/** @type {any} */ q) => !q.dentro_del_dominio);
    for (const k of fuera) leyenda.querySelector("ul")?.append(h("li", null, `✕ ${k.nombre}: fuera del dominio del modelo (${k.o2_pct} % O₂, ${k.presion_kpa} kPa); no se evalúa.`));
    const sin = 19 - (m.cobertura?.length ?? 0);
    leyenda.append(h("p", "inv-nota", `${m.cobertura?.length ?? 0} investigación(es) con O₂ y presión conocidos. ${sin > 0 ? "Las demás aparecerán aquí en cuanto se ingieran sus datos." : ""}`));
  }

  function pintarCapas() {
    capas.replaceChildren(...Object.entries({ entornos: "Entornos", cobertura: "Cobertura", calibracion: "Calibración", tierra: "pO₂ Tierra" }).map(([k, n]) => {
      const b = /** @type {HTMLButtonElement} */ (h("button", "capa", n));
      b.type = "button"; b.setAttribute("aria-pressed", String(visibles[/** @type {keyof typeof visibles} */ (k)]));
      b.addEventListener("click", () => { const kk = /** @type {keyof typeof visibles} */ (k); visibles[kk] = !visibles[kk]; b.setAttribute("aria-pressed", String(visibles[kk])); dibujar(performance.now()); });
      return b;
    }));
  }

  /** Evalúa el modelo real en el punto elegido (no la interpolación). */
  async function evaluar(/** @type {number} */ o2, /** @type {number} */ p) {
    punto = { o2, p };
    sonda.replaceChildren(h("p", "inv-nota", "Evaluando…"));
    dibujar(performance.now());
    try {
      const cuerpo = { fraccion_o2: +(o2 / 100).toFixed(4), presion_kpa: +Math.min(101.325, p).toFixed(2), ...m.condiciones_fijas };
      const r = await fetch("/api/v1/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const res = await r.json();
      if (!punto || punto.o2 !== o2 || punto.p !== p) return;
      punto.res = res;
      const cab = h("p", "sonda-cifra mono", `${res.indice_riesgo.toFixed(0)} / 100 · ${nombreNivel(res.indice_riesgo)}`);
      cab.style.color = `rgb(${colorIndice(res.indice_riesgo)})`;
      sonda.replaceChildren(h("p", "inv-nota", "Punto medido con el modelo"), cab,
        h("p", null, `O₂ ${o2.toFixed(1)} % · ${p.toFixed(1)} kPa · pO₂ ${((o2 / 100) * p).toFixed(1)} kPa`),
        h("p", "inv-nota", `Propagación ${(res.probabilidad_propagacion * 100).toFixed(0)} % · ${res.velocidad_propagacion_mm_s.toFixed(2)} ± ${res.incertidumbre_mm_s.toFixed(2)} mm/s. Es el riesgo SI hubiera ignición, no un evento.`));
      if (o.alCargarEnMonitor) {
        const b = /** @type {HTMLButtonElement} */ (h("button", "boton", "Abrir en el Monitor"));
        b.type = "button";
        b.addEventListener("click", () => o.alCargarEnMonitor?.({ modo: "manual", sliders: { "ctl-o2": +o2.toFixed(1), "ctl-flujo": m.condiciones_fijas.velocidad_flujo_cm_s, "ctl-presion": +p.toFixed(1), "ctl-temp": 300, "ctl-termopar": false } }));
        sonda.append(b);
      }
    } catch (error) {
      console.error("[IGNIS] sonda del mapa", error);
      sonda.replaceChildren(h("p", "vacio", "No se pudo evaluar el punto."));
    }
  }

  const posicion = (/** @type {MouseEvent} */ ev) => { const r = lienzo.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top, W: r.width, H: r.height }; };
  const acotar = (/** @type {{o2:number,p:number}} */ q) => ({ o2: Math.min(m.o2_pct.at(-1), Math.max(m.o2_pct[0], q.o2)), p: Math.min(m.presion_kpa.at(-1), Math.max(m.presion_kpa[0], q.p)) });

  lienzo.addEventListener("mousemove", (ev) => {
    if (!m) return;
    const q = posicion(ev), g = geo(q.W, q.H);
    const zona = zonas.find((z) => Math.hypot(z.x - q.x, z.y - q.y) < z.r);
    lienzo.style.cursor = zona?.tipo === "cobertura" ? "pointer" : "crosshair";
    if (q.x < MARGEN.i || q.x > MARGEN.i + g.w || q.y < MARGEN.s || q.y > MARGEN.s + g.hh) { cursor = null; lectura.textContent = "Haz clic en el mapa para medir un punto con el modelo."; if (!raf) dibujar(performance.now()); return; }
    cursor = acotar(g.inv(q.x, q.y));
    const v = valorEn(m, cursor.o2, cursor.p);
    lectura.textContent = zona ? zona.texto : `O₂ ${cursor.o2.toFixed(1)} % · ${cursor.p.toFixed(1)} kPa · pO₂ ${((cursor.o2 / 100) * cursor.p).toFixed(1)} kPa · índice ≈ ${v.toFixed(0)} (${nombreNivel(v)})`;
    if (!raf) dibujar(performance.now());
  });
  lienzo.addEventListener("mouseleave", () => { cursor = null; if (!raf) dibujar(performance.now()); });
  lienzo.addEventListener("click", (ev) => {
    if (!m) return;
    const q = posicion(ev), g = geo(q.W, q.H);
    const zona = zonas.find((z) => z.tipo === "cobertura" && Math.hypot(z.x - q.x, z.y - q.y) < z.r);
    if (zona && o.alSeleccionar) { o.alSeleccionar(zona.id); return; }
    if (q.x < MARGEN.i || q.x > MARGEN.i + g.w || q.y < MARGEN.s || q.y > MARGEN.s + g.hh) return;
    const c = acotar(g.inv(q.x, q.y));
    evaluar(+c.o2.toFixed(1), +c.p.toFixed(1));
  });
  // Teclado: flechas mueven la sonda, Enter la evalúa (el mapa es operable sin ratón)
  lienzo.addEventListener("keydown", (ev) => {
    if (!m) return;
    const base = punto ?? { o2: 30, p: 70 };
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 2], ArrowDown: [0, -2] }[/** @type {"ArrowLeft"} */ (ev.key)];
    if (!d) return;
    ev.preventDefault();
    const c = acotar({ o2: base.o2 + d[0], p: base.p + d[1] });
    punto = { o2: +c.o2.toFixed(1), p: +c.p.toFixed(1) };
    lectura.textContent = `Sonda: O₂ ${punto.o2} % · ${punto.p} kPa. Pulsa Enter para evaluar.`;
    dibujar(performance.now());
  });
  lienzo.addEventListener("keyup", (ev) => { if (ev.key === "Enter" && punto) evaluar(punto.o2, punto.p); });
  observarTamano(lienzo, () => dibujar(performance.now()));

  return {
    /** Carga (o recarga) los datos; si aparecen investigaciones nuevas en la cobertura, destellan. */
    async cargar() {
      try {
        const r = await fetch("/api/v1/mapa-riesgo");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const datos = await r.json();
        const ids = new Set(datos.cobertura.map((/** @type {any} */ c) => c.id));
        if (m) for (const id of ids) if (!vistas.has(id)) nuevas.set(id, performance.now());
        vistas = /** @type {Set<string>} */ (ids);
        const cambioRejilla = !m || m.indice !== datos.indice;
        m = datos;
        if (cambioRejilla || !fondo) construirFondo();
        pintarLeyenda(); pintarCapas();
        if (!sonda.childElementCount) sonda.replaceChildren(h("p", "inv-nota", "Haz clic en cualquier punto del mapa: IGNIS evalúa su modelo ahí y te dice qué tan crítico es."));
        lectura.textContent ||= "Mueve el cursor sobre el mapa.";
        dibujar(performance.now());
        if (nuevas.size) { arrancar(); setTimeout(() => { nuevas.clear(); }, 2600); }
      } catch (error) {
        console.error("[IGNIS] mapa de riesgo", error);
        lectura.textContent = "No se pudo cargar el mapa (¿el modelo sigue cargando?).";
      }
    },
    /** Pone la sonda en un punto y lo evalúa (p. ej. desde la pestaña de la base lunar). @param {number} o2 @param {number} p */
    sondear(o2, p) { if (m) { const c = acotar({ o2, p }); evaluar(+c.o2.toFixed(1), +c.p.toFixed(1)); } },
    /** Activa o pausa la animación (solo corre con el panel visible). @param {boolean} v */
    activar(v) { activo = v; if (v) { dibujar(performance.now()); arrancar(); } },
  };
}
