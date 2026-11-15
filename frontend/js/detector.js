// @ts-check
/** Panel del detector temporal: estado, probabilidad de evento en el tiempo y lecturas. */
import { obtener } from "./dom.js";

const MUESTRAS = 300; // 30 s a 10 Hz
const UMBRAL = 0.6;
const TEXTO = {
  espera: "Esperando sensores…",
  nominal: "Sin evento: lectura nominal",
  vigilando: "Vigilando: señal sospechosa, sin consenso aún",
  alarma: "ALARMA: evento confirmado por el detector",
};

export function crearPanelDetector() {
  const estado = obtener("detector-estado");
  const texto = obtener("detector-texto");
  const lienzo = /** @type {HTMLCanvasElement} */ (obtener("lienzo-detector"));
  const refs = { p: obtener("detector-p"), dt: obtener("detector-dt"), ir: obtener("detector-ir"), lat: obtener("detector-lat") };
  /** @type {{ p: number, alarma: boolean, fria: number }[]} */ const serie = [];
  let ultimo = "espera";

  /** @param {string} clave */
  function fijarEstado(clave) {
    if (clave === ultimo) return;
    ultimo = clave;
    estado.dataset.estado = clave;
    texto.textContent = TEXTO[clave];
  }

  function dibujar() {
    const caja = lienzo.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(caja.width * dpr)), h = Math.max(1, Math.round(caja.height * dpr));
    if (lienzo.width !== w || lienzo.height !== h) { lienzo.width = w; lienzo.height = h; }
    const ctx = lienzo.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const { width, height } = caja;
    ctx.clearRect(0, 0, width, height);
    const y = (/** @type {number} */ v) => height - 4 - v * (height - 8);
    const x = (/** @type {number} */ i) => width - (serie.length - 1 - i) * (width / (MUESTRAS - 1));
    // Zonas de alarma sombreadas
    ctx.fillStyle = "rgba(255,59,59,0.14)";
    serie.forEach((m, i) => { if (m.alarma) ctx.fillRect(x(i) - width / MUESTRAS, 0, width / MUESTRAS + 1, height); });
    ctx.setLineDash([3, 4]);
    ctx.strokeStyle = "rgba(255,179,71,0.55)";
    ctx.beginPath(); ctx.moveTo(0, y(UMBRAL)); ctx.lineTo(width, y(UMBRAL)); ctx.stroke();
    ctx.setLineDash([]);
    if (serie.length < 2) return;
    ctx.beginPath();
    serie.forEach((m, i) => (i ? ctx.lineTo(x(i), y(m.p)) : ctx.moveTo(x(i), y(m.p))));
    ctx.strokeStyle = "#4fd1ff";
    ctx.lineWidth = 1.8;
    ctx.stroke();
  }
  new ResizeObserver(dibujar).observe(lienzo);

  return {
    /**
     * @param {any} m Mensaje {tipo:"sensores"} del servidor.
     * @returns {{ pFria: number, alarmaNueva: boolean }}
     */
    actualizar(m) {
      const probs = m?.probabilidades ?? {};
      const pFria = Number(probs.LLAMA_FRIA) || 0;
      const p = pFria + (Number(probs.LLAMA_CALIENTE) || 0);
      serie.push({ p, alarma: !!m.alarma_activa, fria: pFria });
      if (serie.length > MUESTRAS) serie.shift();
      fijarEstado(m.alarma_activa ? "alarma" : p >= UMBRAL ? "vigilando" : "nominal");
      refs.p.textContent = `${(p * 100).toFixed(0)} %`;
      refs.dt.textContent = `${Number(m.canales?.delta_t_k ?? 0).toFixed(0)} K`;
      refs.ir.textContent = Number(m.canales?.ir_rel ?? 0).toFixed(2);
      refs.lat.textContent = `${Number(m.latencia_ms ?? 0).toFixed(1)} ms`;
      dibujar();
      return { pFria, alarmaNueva: !!m.alarma_nueva };
    },
    /** Limpia la serie al cambiar de señal. */
    reiniciar() {
      serie.length = 0;
      ultimo = "";
      fijarEstado("espera");
      dibujar();
    },
    /** Sin conexión: vuelve a "esperando". */
    sinSenal() {
      fijarEstado("espera");
    },
  };
}
