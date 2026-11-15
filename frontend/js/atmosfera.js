// @ts-check
/**
 * Pestaña «Base lunar»: evalúa solo la atmósfera esperada (≥ 30 % O₂, ≤ 70,3 kPa) frente a la ISS, con controles en vivo.
 * Consume POST /api/v1/preset/lunar. Todo texto del servidor entra con textContent.
 */
import { h } from "./dom.js";
import { colorIndice, nombreNivel } from "./mapa.js";
import { porcentajes } from "./confianza.js";

// Pesos del índice del modelo (docs/science.md): 100·(0.55·P(propaga) + 0.30·tanh(v/4.74) + 0.15·P(llama fría)).
const PESO = { prop: 55, vel: 30, fria: 15 }, ESCALA_V = 4.74;
/** Descompone el índice en sus tres aportes. Devuelve null si no cuadra con el valor del servidor (entonces no se muestra). @param {any} ev */
export function descomponerIndice(ev) {
  const prop = PESO.prop * (ev.probabilidad_propagacion ?? 0), vel = PESO.vel * Math.tanh((ev.velocidad_propagacion_mm_s ?? 0) / ESCALA_V), fria = PESO.fria * (ev.probabilidad_llama_fria ?? 0);
  return Math.abs(prop + vel + fria - ev.indice_riesgo) <= 0.6 ? { prop, vel, fria } : null;
}

/** Anillo de indicador (0-100) animado por CSS. @param {string} titulo */
function anillo(titulo) {
  const el = h("div", "anillo"); el.setAttribute("role", "img");
  const cifra = h("strong", "anillo-v mono", "—"), nivel = h("span", "anillo-n", ""), t = h("span", "anillo-t", titulo);
  el.append(cifra, nivel);
  const caja = h("figure", "anillo-caja"); caja.append(el, t);
  return {
    caja,
    /** @param {number} v */
    poner(v) { el.style.setProperty("--v", String(Math.round(v))); el.style.setProperty("--c", `rgb(${colorIndice(v)})`); cifra.textContent = v.toFixed(0); nivel.textContent = nombreNivel(v); el.setAttribute("aria-label", `${titulo}: ${v.toFixed(0)} de 100, ${nombreNivel(v)}`); },
  };
}

/**
 * @param {{ contenedor: HTMLElement, alCargarEnMonitor?: (m: { modo: string, sliders: Record<string, number|boolean> }) => void, alVerEnMapa?: (o2: number, p: number) => void }} o
 */
export function crearAtmosfera(o) {
  const luna = anillo("Base lunar"), iss = anillo("ISS (referencia)");
  const delta = h("p", "luna-delta mono"), explic = h("p", "luna-explicacion"), pO2 = h("p", "inv-nota"), acciones = h("div", "inv-fila"), sup = h("ul", "luna-supuestos");
  const mk = (/** @type {string} */ id, /** @type {string} */ nombre, /** @type {number} */ min, /** @type {number} */ max, /** @type {number} */ paso, /** @type {number} */ v) => {
    const l = h("label", "control"), val = h("output", "mono"), inp = /** @type {HTMLInputElement} */ (h("input"));
    inp.type = "range"; inp.id = id; inp.min = String(min); inp.max = String(max); inp.step = String(paso); inp.value = String(v);
    l.append(h("span", null, nombre), val, inp);
    return { l, inp, val };
  };
  const sO2 = mk("luna-o2", "O₂", 30, 40, 0.5, 30), sP = mk("luna-p", "Presión", 35, 70.3, 0.1, 70), sF = mk("luna-f", "Flujo de aire", 0, 50, 1, 10);
  const selMat = /** @type {HTMLSelectElement} */ (h("select")); selMat.id = "luna-mat";
  for (const [v, n] of [["sibal", "SIBAL (algodón/fibra de vidrio, Saffire)"], ["pmma", "PMMA (acrílico)"], ["celulosa", "Celulosa (algodón/papel)"]]) { const op = h("option", null, n); op.value = v; selMat.append(op); }
  const lMat = h("label", "control"); lMat.append(h("span", null, "Material"), selMat);
  const desglose = h("div", "luna-desglose");
  const aprende = h("details", "luna-det"); aprende.open = true;
  aprende.append(h("summary", null, "Cómo leer esta pantalla"), h("ul", "luna-supuestos"));
  aprende.querySelector("ul")?.append(
    h("li", null, "Pregunta que responde: si en la base lunar ocurriera una ignición, ¿cuánto más grave sería que en la ISS? No dice que haya fuego; mide el potencial."),
    h("li", null, "¿Por qué O₂ y presión? Son las dos variables que el reto fija para el hábitat (≥ 30 % de O₂, ≤ 70,3 kPa) y las que más cambian la inflamabilidad. Flujo de aire y material los eliges aquí abajo; el resto se fija en valores de referencia."),
    h("li", null, "¿Por qué casi nunca llega a 100? El índice suma tres aportes: 55 pts por probabilidad de propagación, 30 por velocidad de llama (satura con tanh: duplicar la velocidad no duplica el riesgo) y 15 por llama fría, que no aplica a estos sólidos. Con el máximo del dominio (40 % de O₂) el techo práctico ronda 83."));
  o.contenedor.setAttribute("data-luna", "1");
  const btnMonitor = /** @type {HTMLButtonElement} */ (h("button", "boton", "Abrir en el Monitor")), btnMapa = /** @type {HTMLButtonElement} */ (h("button", "boton boton-sec", "Verla en el mapa"));
  btnMonitor.type = btnMapa.type = "button";
  acciones.append(btnMonitor, btnMapa);
  const det = h("details", "luna-det"); det.append(h("summary", null, "Qué se supone en este cálculo"), sup);
  const anillos = h("div", "luna-anillos"); anillos.append(luna.caja, h("div", "luna-vs", "vs"), iss.caja);
  o.contenedor.replaceChildren(h("p", "inv-nota", "Atmósfera esperada en la base lunar según el reto: al menos 30 % de O₂ y como máximo 70,3 kPa (10,2 psi). Mueve los controles y compárala con la ISS."),
    aprende, anillos, delta, explic, desglose, pO2, sO2.l, sP.l, sF.l, lMat, acciones, det);

  /** @type {any} */ let ultimo = null;
  let temporizador = 0, solicitud = 0;
  const etiquetas = () => { sO2.val.textContent = `${(+sO2.inp.value).toFixed(1)} %`; sP.val.textContent = `${(+sP.inp.value).toFixed(1)} kPa`; sF.val.textContent = `${(+sF.inp.value).toFixed(0)} cm/s`; };
  /** Cuánto de este resultado está respaldado: O₂ y presión salen del texto del reto; lo demás lo fija el usuario o el modelo. */
  function respaldo() {
    const n = { verificado: 2, supuesto: 4 }, pc = porcentajes(n);
    const caja = h("div", "luna-respaldo"), barra = h("div", "conf-apilada"); barra.setAttribute("role", "img"); barra.setAttribute("aria-label", `Respaldo: ${pc.verificado} % verificado, ${pc.supuesto} % supuesto`);
    for (const k of ["verificado", "supuesto"]) { const sp = h("span", `conf-${k}`, `${pc[k]} % ${k}`); sp.style.flexGrow = String(n[/** @type {"verificado"} */ (k)]); barra.append(sp); }
    caja.append(h("p", "inv-nota", "Respaldo de este resultado (6 entradas del modelo)"), barra,
      h("p", "inv-nota", "Verificado: O₂ (≥ 30 %) y presión (≤ 70,3 kPa), del texto del reto NASA 2026. Supuesto: flujo y material (los eliges aquí), espesor (0,2 mm) y temperatura (295 K), valores de referencia del modelo. Para una investigación concreta, abre la pestaña Confianza."));
    return caja;
  }
  /** Barra apilada con los tres aportes del índice. @param {string} nombre @param {any} ev */
  function barraDesglose(nombre, ev) {
    const fila = h("div", "desglose-fila"), d = descomponerIndice(ev);
    fila.append(h("span", "desglose-n", nombre));
    const barra = h("div", "desglose-barra"); barra.setAttribute("role", "img");
    if (!d) { fila.append(h("span", "inv-nota", `Índice ${ev.indice_riesgo.toFixed(0)} (desglose no disponible)`)); return fila; }
    barra.setAttribute("aria-label", `${nombre}: propagación ${d.prop.toFixed(0)}, velocidad ${d.vel.toFixed(0)}, llama fría ${d.fria.toFixed(0)} de 100`);
    for (const [clave, v, t] of /** @type {[string, number, string][]} */ ([["prop", d.prop, "Propagación"], ["vel", d.vel, "Velocidad"], ["fria", d.fria, "Llama fría"]])) { const sg = h("span", `desglose-${clave}`); sg.style.width = `${v}%`; sg.title = `${t}: ${v.toFixed(1)} pts`; barra.append(sg); }
    fila.append(barra, h("span", "mono", `${ev.indice_riesgo.toFixed(0)}  = ${d.prop.toFixed(0)} + ${d.vel.toFixed(0)} + ${d.fria.toFixed(0)}`));
    return fila;
  }

  async function evaluar() {
    const mia = ++solicitud;
    o.contenedor.setAttribute("aria-busy", "true");
    try {
      const r = await fetch("/api/v1/preset/lunar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fraccion_o2: +sO2.inp.value / 100, presion_kpa: +sP.inp.value, velocidad_flujo_cm_s: +sF.inp.value, material: selMat.value }) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (mia !== solicitud) return;
      ultimo = d;
      luna.poner(d.evaluacion.indice_riesgo); iss.poner(d.referencia_iss.indice_riesgo);
      const dl = d.delta_indice_vs_iss;
      delta.textContent = `${dl > 0 ? "+" : dl < 0 ? "−" : "±"}${Math.abs(dl).toFixed(1)} pts frente a la ISS`;
      delta.dataset.signo = dl > 0.05 ? "mas" : dl < -0.05 ? "menos" : "igual";
      explic.textContent = d.explicacion;
      desglose.replaceChildren(h("p", "inv-nota", "De qué se compone el índice (propagación + velocidad + llama fría; el máximo teórico es 100)"), barraDesglose("Base lunar", d.evaluacion), barraDesglose("ISS", d.referencia_iss), respaldo());
      pO2.textContent = `pO₂: ${d.ppo2_kpa} kPa en la base lunar frente a ${d.ppo2_iss_kpa} kPa en la ISS. El modelo depende de la composición y de la presión, no solo de la pO₂.`;
      sup.replaceChildren(...[...d.advertencias, ...d.supuestos].map((/** @type {string} */ t) => h("li", null, t)));
      btnMonitor.disabled = !o.alCargarEnMonitor; btnMapa.disabled = !o.alVerEnMapa;
    } catch (error) {
      console.error("[IGNIS] preset lunar", error);
      explic.textContent = "No se pudo evaluar (¿el modelo sigue cargando?).";
    } finally {
      if (mia === solicitud) o.contenedor.setAttribute("aria-busy", "false");
    }
  }
  const programar = () => { etiquetas(); clearTimeout(temporizador); temporizador = /** @type {any} */ (setTimeout(evaluar, 220)); };
  sO2.inp.addEventListener("input", programar); sP.inp.addEventListener("input", programar); sF.inp.addEventListener("input", programar); selMat.addEventListener("change", programar);
  btnMonitor.addEventListener("click", () => ultimo && o.alCargarEnMonitor?.(ultimo.monitor));
  btnMapa.addEventListener("click", () => o.alVerEnMapa?.(+sO2.inp.value, +sP.inp.value));
  etiquetas();

  return { activar() { if (!ultimo) evaluar(); } };
}
