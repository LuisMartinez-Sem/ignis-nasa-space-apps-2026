// @ts-check
/**
 * Panel del hardware (Arduino): estado en vivo, última lectura, gráfica y vínculo opcional con el gemelo digital.
 * Consume GET /api/v1/hardware/lectura (cada 2 s mientras la pestaña esté visible). Todo texto entra con textContent.
 */
import { h, obtener } from "./dom.js";
import { prepararLienzo } from "./lienzo.js";

const kelvinA_C = (/** @type {number} */ k) => k - 273.15;

/** Texto del chip según el estado. @param {any} d */
export function textoChip(d) {
  if (!d || d.ultimo_dato_s === null) return "Arduino: sin conexión";
  if (!d.conectado) return `Arduino: sin señal (${d.ultimo_dato_s.toFixed(0)} s)`;
  return d.lectura ? `Arduino · ${kelvinA_C(d.lectura.temperatura_k).toFixed(1)} °C` : "Arduino · en línea";
}

/** @param {{ alLecturaReaccion?: (tempK: number) => void, alAbrir?: () => void }} [o] */
export function crearHardware(o = {}) {
  const chip = obtener("chip-hardware"), panel = obtener("panel-hardware");
  const estado = h("p", "hw-estado"), cifras = h("div", "hw-cifras"), nota = h("p", "inv-nota"), lienzo = /** @type {HTMLCanvasElement} */ (h("canvas", "hw-lienzo"));
  lienzo.setAttribute("role", "img"); lienzo.setAttribute("aria-label", "Temperatura reciente del sensor");
  const enlace = /** @type {HTMLInputElement} */ (h("input")); enlace.type = "checkbox"; enlace.id = "hw-gemelo";
  const etq = /** @type {HTMLLabelElement} */ (h("label", "casilla")); etq.htmlFor = "hw-gemelo"; etq.append(enlace, document.createTextNode(" Enviar la temperatura al gemelo digital"));
  panel.replaceChildren(h("h3", "panel-titulo", "Hardware"), estado, cifras, lienzo, etq, nota);
  /** @type {any} */ let d = null;
  let temporizador = 0;

  function dibujar() {
    if (!d || lienzo.offsetWidth === 0) return;  // sin datos o con el Monitor oculto
    const { ctx, W, H } = prepararLienzo(lienzo);
    ctx.clearRect(0, 0, W, H);
    const hist = d.historial ?? [];
    if (hist.length < 2) { ctx.fillStyle = "#98a9c2"; ctx.font = "11px 'JetBrains Mono', monospace"; ctx.fillText("Esperando lecturas…", 8, H / 2); return; }
    const ts = hist.map((/** @type {any} */ x) => kelvinA_C(x.temperatura_k)), lo = Math.min(...ts) - 0.5, hi = Math.max(...ts) + 0.5, tmax = Math.max(...hist.map((/** @type {any} */ x) => x.hace_s), 1);
    ctx.strokeStyle = "#4fd1ff"; ctx.lineWidth = 2; ctx.beginPath();
    hist.forEach((/** @type {any} */ x, /** @type {number} */ i) => { const px = 6 + (1 - x.hace_s / tmax) * (W - 12), py = H - 8 - ((ts[i] - lo) / (hi - lo)) * (H - 16); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.stroke();
    ctx.fillStyle = "#98a9c2"; ctx.font = "10px 'JetBrains Mono', monospace"; ctx.fillText(`${hi.toFixed(1)} °C`, 6, 11); ctx.fillText(`${lo.toFixed(1)} °C`, 6, H - 2);
  }

  function pintar() {
    chip.textContent = textoChip(d);
    chip.dataset.estado = d?.conectado ? "conectado" : d?.ultimo_dato_s === null || !d ? "desconectado" : "conectando";
    const l = d?.lectura;
    estado.textContent = !d || d.ultimo_dato_s === null ? "Sin conexión. Ejecuta hardware_bridge.py con el Arduino conectado." : d.conectado ? `${d.dispositivo}: en línea (último dato hace ${d.ultimo_dato_s.toFixed(1)} s)` : `${d.dispositivo}: sin señal desde hace ${d.ultimo_dato_s.toFixed(0)} s`;
    const punto = document.getElementById("hw-mini-punto"), mini = document.getElementById("hw-mini-texto");
    if (punto) punto.dataset.estado = chip.dataset.estado ?? "desconectado";
    if (mini) mini.textContent = d?.conectado && l ? `${textoChip(d)} · ${l.campo === "reaccion" ? "zona de reacción" : "aire ambiente"}${l.indice_riesgo === null ? "" : ` · índice ${l.indice_riesgo.toFixed(0)}`}` : textoChip(d).replace("Arduino", "Hardware");
    cifras.replaceChildren();
    if (l) {
      for (const [k, v] of /** @type {[string, string][]} */ ([["Temperatura", `${kelvinA_C(l.temperatura_k).toFixed(1)} °C`], ["Mide", l.campo === "reaccion" ? "zona de reacción" : "aire ambiente"], ["Índice", l.indice_riesgo === null ? "—" : `${l.indice_riesgo.toFixed(0)} · ${l.nivel_riesgo ?? ""}`]])) {
        const c = h("div", "pill"); c.append(h("span", "pill-k", k), h("strong", "pill-v mono", v)); cifras.append(c);
      }
    }
    const reaccion = l?.campo === "reaccion";
    enlace.disabled = !reaccion;
    if (!reaccion) enlace.checked = false;
    nota.textContent = reaccion ? "Con un termopar sobre la llama, la temperatura mueve el control «T reacción» del Monitor y cambia el índice y la llama fría."
      : "El DHT11 mide el aire (0-50 °C): cambia el índice del modelo solo unos puntos y no mueve la llama del gemelo. Un termopar (--campo reaccion) sí lo haría.";
    if (enlace.checked && reaccion && d.conectado) o.alLecturaReaccion?.(l.temperatura_k);
    dibujar();
  }

  async function sondear() {
    if (document.hidden) return;
    try {
      const r = await fetch("/api/v1/hardware/lectura");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      d = await r.json();
    } catch { d = null; }
    pintar();
  }

  chip.addEventListener("click", () => o.alAbrir?.());
  document.getElementById("hw-mini-abrir")?.addEventListener("click", () => o.alAbrir?.());
  sondear();
  temporizador = /** @type {any} */ (setInterval(sondear, 2000));
  return { detener() { clearInterval(temporizador); } };
}
