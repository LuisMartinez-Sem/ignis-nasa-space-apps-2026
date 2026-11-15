// @ts-check
/**
 * Reproductor cinemático: reproduce un guion (escenario o incidente) evaluado por los modelos de IGNIS.
 * Controles: escenario, play/pausa/reinicio, velocidad 0.5×/1×/2×/10×, doble línea de tiempo con marcas
 * clicables (referencia humana arriba, IGNIS abajo), desglose de latencia y "qué pasaría si".
 * El módulo solo decide QUÉ frame toca; main.js decide cómo pintarlo (misma ruta que el modo en vivo).
 * Todo texto externo entra con textContent.
 */
import { h, obtener, s } from "./dom.js";

export const VELOCIDADES = [0.5, 1, 2, 10];
const INTERVALO_WHATIF_MS = 250;
const ANCHO = 900, ALTO = 150, MARGEN_I = 104, MARGEN_D = 28;

/**
 * Frame que corresponde al instante `t` (segundos) y su índice; acota a los extremos.
 * @param {{ frames: any[] }} guion @param {number} t
 */
export function frameEn(guion, t) {
  const i = Math.min(guion.frames.length - 1, Math.max(0, Math.floor(t)));
  return { indice: i, frame: guion.frames[i] };
}

/**
 * Avanza el tiempo simulado, respetando velocidad y fin del guion.
 * @param {number} t @param {number} dtReal @param {number} velocidad @param {number} duracion
 * @returns {{ t: number, terminado: boolean }}
 */
export function avanzar(t, dtReal, velocidad, duracion) {
  const nuevo = t + dtReal * velocidad;
  return nuevo >= duracion ? { t: duracion, terminado: true } : { t: nuevo, terminado: false };
}

/** Desglose de latencia sensor → TCN → copiloto con lo MEDIDO. @param {any} lat @param {number|null} rttMs */
export function desglose(lat, rttMs) {
  const tcn = lat?.tcn_ms_medio ?? null;
  const modelo = lat?.modelo_ms_medio ?? null;
  const partes = [
    { etapa: "Sensor (muestreo 10 Hz)", ms: lat?.muestreo_ms ?? 100, nota: "periodo nominal, no medido" },
    { etapa: "Detector TCN", ms: tcn, nota: tcn === null ? "detector no disponible" : `p95 ${Number(lat.tcn_ms_p95).toFixed(1)} ms (medido)` },
    { etapa: "Copiloto (modelo + red)", ms: modelo === null && rttMs === null ? null : (modelo ?? 0) + (rttMs ?? 0),
      nota: `${modelo === null ? "—" : modelo.toFixed(2)} ms modelo (servidor) + ${rttMs === null ? "—" : rttMs.toFixed(0)} ms ida y vuelta (este navegador)` },
  ];
  const total = partes.reduce((a, p) => a + (p.ms ?? 0), 0);
  return { partes, total };
}

/**
 * @param {{
 *   alFrame: (frame: any, guion: any, t: number) => void,
 *   alCargar: (guion: any) => void,
 *   alEstado: (reproduciendo: boolean) => void,
 *   alWhatIf: (condiciones: any|null) => void,
 * }} ganchos
 */
export function crearReproductor(ganchos) {
  const selector = /** @type {HTMLSelectElement} */ (obtener("rep-escenario"));
  const botonPlay = /** @type {HTMLButtonElement} */ (obtener("rep-play"));
  const botonReset = /** @type {HTMLButtonElement} */ (obtener("rep-reset"));
  const reloj = obtener("rep-tiempo");
  const info = obtener("rep-info");
  const lineas = obtener("rep-lineas");
  const latencia = obtener("rep-latencia");
  const estadoWhatIf = obtener("rep-whatif-estado");
  const botonesVel = /** @type {HTMLButtonElement[]} */ ([...document.querySelectorAll("[data-rep-vel]")]);
  const sliders = {
    fraccion_o2: /** @type {HTMLInputElement} */ (obtener("wi-o2")),
    velocidad_flujo_cm_s: /** @type {HTMLInputElement} */ (obtener("wi-flujo")),
    temperatura_reaccion_k: /** @type {HTMLInputElement} */ (obtener("wi-treac")),
  };
  const salidas = { fraccion_o2: obtener("wi-o2-v"), velocidad_flujo_cm_s: obtener("wi-flujo-v"), temperatura_reaccion_k: obtener("wi-treac-v") };

  /** @type {any|null} */ let guion = null;
  let t = 0, velocidad = 1, reproduciendo = false, ultimoI = -1, marco = 0, ultimoTick = 0;
  /** @type {any|null} */ let whatIf = null;
  /** @type {number|null} */ let rttMs = null;
  /** @type {SVGLineElement|null} */ let cabezal = null;
  /** @type {SVGLineElement[]} */ let progresos = [];
  let temporizadorWhatIf = 0;
  let listaCargada = false;

  const formatoT = (/** @type {number} */ x) => `${String(Math.floor(x / 60)).padStart(2, "0")}:${(x % 60).toFixed(1).padStart(4, "0")}`;
  const x = (/** @type {number} */ seg) => MARGEN_I + (seg / Math.max(1, guion?.duracion_s ?? 1)) * (ANCHO - MARGEN_I - MARGEN_D);

  function pintarReloj() {
    reloj.textContent = `${formatoT(t)} / ${formatoT(guion?.duracion_s ?? 0)}`;
    if (cabezal) { cabezal.setAttribute("x1", String(x(t))); cabezal.setAttribute("x2", String(x(t))); }
    for (const p of progresos) p.setAttribute("x2", String(x(t)));
  }

  /** @param {number} seg */
  function saltar(seg) {
    if (!guion) return;
    t = Math.min(guion.duracion_s, Math.max(0, seg));
    emitir(true);
  }

  /** @param {boolean} forzar */
  function emitir(forzar) {
    if (!guion) return;
    const { indice, frame } = frameEn(guion, t);
    pintarReloj();
    if (indice === ultimoI && !forzar) return;
    ultimoI = indice;
    ganchos.alFrame(frame, guion, t);
    if (!whatIf) sincronizarSliders(frame);
  }

  /** @param {any} frame */
  function sincronizarSliders(frame) {
    const c = frame.condiciones;
    const hay = frame.indice_riesgo !== null && frame.indice_riesgo !== undefined;
    for (const [k, el] of Object.entries(sliders)) {
      const valor = typeof c[k] === "number" ? c[k] : Number(el.min);
      el.value = String(k === "fraccion_o2" ? Math.round(valor * 1000) / 10 : valor);
      el.disabled = !hay;
      pintarSalida(/** @type {keyof typeof sliders} */ (k));
    }
    estadoWhatIf.textContent = hay ? "Sincronizado con la reproducción. Mueve un control para explorar." : "Sin evaluación del modelo en este instante (fuera de dominio).";
  }

  /** @param {keyof typeof sliders} k */
  function pintarSalida(k) {
    const v = Number(sliders[k].value);
    salidas[k].textContent = k === "fraccion_o2" ? `${v.toFixed(1)} %` : k === "velocidad_flujo_cm_s" ? `${v.toFixed(0)} cm/s` : `${v.toFixed(0)} K`;
  }

  function leerWhatIf() {
    const { frame } = frameEn(/** @type {any} */ (guion), t);
    return { ...frame.condiciones, fraccion_o2: Number(sliders.fraccion_o2.value) / 100,
      velocidad_flujo_cm_s: Number(sliders.velocidad_flujo_cm_s.value), temperatura_reaccion_k: Number(sliders.temperatura_reaccion_k.value) };
  }

  for (const [k, el] of Object.entries(sliders)) {
    el.addEventListener("input", () => {
      pintarSalida(/** @type {keyof typeof sliders} */ (k));
      whatIf = leerWhatIf();
      estadoWhatIf.textContent = "Qué pasaría si: la reproducción NO cambia; se compara con el instante actual.";
      clearTimeout(temporizadorWhatIf);
      temporizadorWhatIf = window.setTimeout(() => ganchos.alWhatIf(whatIf), INTERVALO_WHATIF_MS);
    });
  }
  obtener("wi-volver").addEventListener("click", () => {
    whatIf = null;
    ganchos.alWhatIf(null);
    if (guion) sincronizarSliders(frameEn(guion, t).frame);
  });

  function pintarLineas() {
    lineas.replaceChildren();
    if (!guion) return;
    const svg = s("svg", { viewBox: `0 0 ${ANCHO} ${ALTO}`, class: "rep-svg", role: "group", "aria-label": "Doble línea de tiempo: referencia humana arriba, IGNIS abajo. Cada marca es un botón." });
    const carriles = [["Referencia", 64, guion.marcas_referencia, "ref"], ["IGNIS", 114, guion.marcas_ignis, "ign"]];
    progresos = [];
    const paso = guion.duracion_s > 240 ? 60 : guion.duracion_s > 90 ? 20 : 10;
    for (let seg = 0; seg <= guion.duracion_s; seg += paso) {
      svg.append(s("line", { x1: x(seg), x2: x(seg), y1: 14, y2: ALTO - 18, class: "rep-rejilla" }));
      const tx = s("text", { x: x(seg), y: ALTO - 4, class: "rep-eje", "text-anchor": "middle" });
      tx.textContent = `${seg}s`;
      svg.append(tx);
    }
    for (const [nombre, y, marcas, clase] of /** @type {[string, number, any[], string][]} */ (carriles)) {
      svg.append(s("line", { x1: MARGEN_I, x2: ANCHO - MARGEN_D, y1: y, y2: y, class: "rep-carril" }));
      const prog = /** @type {SVGLineElement} */ (s("line", { x1: MARGEN_I, x2: x(t), y1: y, y2: y, class: `rep-progreso rep-progreso-${clase}` }));
      progresos.push(prog); svg.append(prog);
      const rot = s("text", { x: 8, y: y + 4, class: "rep-rotulo" });
      rot.textContent = nombre;
      svg.append(rot);
      let previo = -1e9, nivel = 0, n = 0;
      for (const m of /** @type {any[]} */ ([...marcas].sort((a, b) => a.t_s - b.t_s))) {
        n += 1; m._n = n;
        nivel = x(m.t_s) - previo < 20 ? nivel + 1 : 0; previo = x(m.t_s);
        m._dy = [0, -16, 16, -32][nivel % 4];
        const g = s("g", { class: `rep-marca rep-marca-${clase}`, tabindex: 0, role: "button", "data-confianza": m.confianza,
          "aria-label": `${m.texto}, a los ${m.t_s} segundos. Ir a este instante.` });
        const titulo = s("title");
        titulo.textContent = `${m.t_s.toFixed(0)} s · ${m.texto} (${m.confianza})`;
        const num = s("text", { x: x(m.t_s), y: y + m._dy + 3.5, class: "rep-num", "text-anchor": "middle" }); num.textContent = String(m._n);
        g.append(titulo, s("circle", { cx: x(m.t_s), cy: y + m._dy, r: 9 }), num);
        const ir = () => saltar(m.t_s);
        g.addEventListener("click", ir);
        g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ir(); } });
        svg.append(g);
      }
    }
    cabezal = /** @type {SVGLineElement} */ (s("line", { x1: x(t), x2: x(t), y1: 8, y2: ALTO - 18, class: "rep-cabezal" }));
    svg.append(cabezal);
    svg.addEventListener("click", (e) => {
      if (/** @type {Element} */ (e.target).closest(".rep-marca")) return;
      const caja = svg.getBoundingClientRect();
      const px = ((e.clientX - caja.left) / caja.width) * ANCHO;
      saltar(((px - MARGEN_I) / (ANCHO - MARGEN_I - MARGEN_D)) * guion.duracion_s);
    });
    lineas.append(svg);
    const lista = document.createElement("ol"); lista.className = "rep-lista";
    for (const [nombre, , marcas, clase] of /** @type {[string, number, any[], string][]} */ (carriles)) {
      for (const m of /** @type {any[]} */ ([...marcas].sort((a, b) => a.t_s - b.t_s))) {
        const li = document.createElement("li"), bt = document.createElement("button");
        bt.type = "button"; bt.className = `rep-item rep-item-${clase}`; bt.dataset.confianza = m.confianza;
        bt.textContent = `${nombre} ${m._n} · ${m.t_s.toFixed(0)} s — ${m.texto} (${m.confianza})`;
        bt.addEventListener("click", () => saltar(m.t_s)); li.append(bt); lista.append(li);
      }
    }
    lineas.append(lista);
  }

  function pintarLatencia() {
    latencia.replaceChildren();
    if (!guion) return;
    const { partes, total } = desglose(guion.latencias_ms, rttMs);
    const ol = h("ol", "rep-lat-lista");
    for (const p of partes) {
      const li = h("li", "rep-lat-item");
      li.append(h("span", "rep-lat-etapa", p.etapa), h("strong", "mono", p.ms === null ? "—" : `${p.ms.toFixed(p.ms < 10 ? 2 : 0)} ms`), h("span", "rep-lat-nota", p.nota));
      ol.append(li);
    }
    latencia.append(ol, h("p", "rep-lat-total mono", `Sensor → alerta ≈ ${total.toFixed(0)} ms (suma de etapas)`));
  }

  async function medirRtt() {
    const inicio = performance.now();
    try {
      const r = await fetch("/health");
      if (r.ok) rttMs = performance.now() - inicio;
    } catch { rttMs = null; }
    pintarLatencia();
  }

  function pausar() {
    reproduciendo = false;
    cancelAnimationFrame(marco);
    botonPlay.textContent = "▶ Reproducir";
    botonPlay.setAttribute("aria-pressed", "false");
    ganchos.alEstado(false);
  }

  /** @param {number} ahora */
  function paso(ahora) {
    if (!reproduciendo || !guion) return;
    const dt = Math.min(0.25, (ahora - ultimoTick) / 1000);
    ultimoTick = ahora;
    const r = avanzar(t, dt, velocidad, guion.duracion_s);
    t = r.t;
    emitir(false);
    if (r.terminado) { pausar(); return; }
    marco = requestAnimationFrame(paso);
  }

  function reproducir() {
    if (!guion) return;
    if (t >= guion.duracion_s) t = 0;
    reproduciendo = true;
    botonPlay.textContent = "❚❚ Pausa";
    botonPlay.setAttribute("aria-pressed", "true");
    ultimoTick = performance.now();
    ganchos.alEstado(true);
    emitir(true);
    marco = requestAnimationFrame(paso);
  }

  botonPlay.addEventListener("click", () => (reproduciendo ? pausar() : reproducir()));
  botonReset.addEventListener("click", () => { pausar(); t = 0; whatIf = null; ganchos.alWhatIf(null); emitir(true); });
  for (const b of botonesVel) {
    b.addEventListener("click", () => {
      velocidad = Number(b.dataset.repVel);
      for (const o of botonesVel) o.setAttribute("aria-pressed", String(o === b));
    });
  }
  window.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || !guion || document.body.dataset.fuente !== "reproduccion") return;
    const tag = /** @type {HTMLElement} */ (e.target).tagName;
    if (["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(tag)) return;
    e.preventDefault();
    botonPlay.click();
  });

  async function cargarLista() {
    try {
      const r = await fetch("/api/v1/escenarios");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      /** @type {any[]} */ const lista = await r.json();
      const grupos = { escenario: h("optgroup"), incidente: h("optgroup") };
      grupos.escenario.label = "Escenarios";
      grupos.incidente.label = "Incidentes históricos";
      for (const e of lista) {
        const op = /** @type {HTMLOptionElement} */ (h("option", null, `${e.nombre} · ${Math.round(e.duracion_s)} s`));
        op.value = e.id;
        grupos[/** @type {"escenario"|"incidente"} */ (e.grupo)]?.append(op);
      }
      selector.replaceChildren(grupos.escenario, grupos.incidente);
      listaCargada = true;
      await cargarGuion(selector.value);
    } catch (error) {
      info.textContent = "No se pudo cargar la lista de escenarios.";
      console.error("[IGNIS] escenarios", error);
    }
  }

  /** @param {string} id */
  async function cargarGuion(id) {
    pausar();
    info.textContent = "Evaluando el guion con los modelos…";
    try {
      const r = await fetch(`/api/v1/escenarios/${encodeURIComponent(id)}/reproduccion`);
      if (r.status === 503) { info.textContent = "Los modelos aún se están cargando. Reintentando…"; setTimeout(() => selector.value === id && cargarGuion(id), 3000); return; }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      guion = await r.json();
      t = 0; ultimoI = -1; whatIf = null;
      info.replaceChildren(h("strong", null, guion.nombre), h("span", "rep-conf", ` · ${guion.confianza}`), h("p", "rep-desc", guion.descripcion), h("p", "rep-aviso", guion.advertencia));
      pintarLineas();
      pintarLatencia();
      ganchos.alCargar(guion);
      emitir(true);
    } catch (error) {
      info.textContent = "No se pudo evaluar este guion.";
      console.error("[IGNIS] reproduccion", error);
    }
  }
  selector.addEventListener("change", () => cargarGuion(selector.value));

  return {
    /** Primera activación: carga lista y mide la latencia de red. */
    activar() {
      if (!listaCargada) { cargarLista(); medirRtt(); }
    },
    pausar,
    get reproduciendo() { return reproduciendo; },
    get whatIf() { return whatIf; },
    /** Actualiza el RTT medido por otra parte del HUD (p. ej. la consulta del What-If). @param {number} ms */
    registrarRtt(ms) { rttMs = ms; pintarLatencia(); },
  };
}
