// @ts-check
/** Soporte de canvas nítido (HiDPI) y responsivo para los gráficos de Investigaciones. */

export const reducirMovimiento = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Mínimo de sobremuestreo: en pantallas de 1 px por píxel CSS (laptops 1366×768) dibujar a 2× evita el aspecto borroso. */
const SOBREMUESTREO_MIN = 2;

/**
 * Ajusta el canvas a su tamaño CSS × densidad de píxeles y devuelve el contexto en píxeles CSS.
 * El tamaño CSS lo decide el diseño (la caja que lo contiene), nunca el propio canvas: así no hay bucles de crecimiento.
 * @param {HTMLCanvasElement} canvas
 */
export function prepararLienzo(canvas) {
  const dpr = Math.min(3, Math.max(SOBREMUESTREO_MIN, globalThis.devicePixelRatio || 1));
  const r = canvas.getBoundingClientRect();
  const W = Math.max(240, r.width), H = Math.max(180, r.height);
  const bw = Math.round(W * dpr), bh = Math.round(H * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
  const ctx = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
  ctx.setTransform(bw / W, 0, 0, bh / H, 0, 0);
  return { ctx, W, H };
}

/**
 * Redibuja cuando el canvas cambia de tamaño (ventana, pestañas, zoom, barras laterales) o vuelve a ser visible.
 * @param {HTMLCanvasElement} canvas @param {() => void} redibujar
 * @returns {() => void} función para forzar un redibujado (p. ej. al mostrar la pestaña)
 */
export function observarTamano(canvas, redibujar) {
  let ultimo = "", pendiente = 0;
  const medir = () => {
    pendiente = 0;
    const r = canvas.getBoundingClientRect();
    const k = `${Math.round(r.width)}x${Math.round(r.height)}@${globalThis.devicePixelRatio || 1}`;
    if (r.width > 0 && r.height > 0 && k !== ultimo) { ultimo = k; redibujar(); }
  };
  const programar = () => { if (!pendiente) pendiente = requestAnimationFrame(medir); };
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(programar).observe(canvas);
  globalThis.addEventListener?.("resize", programar);
  return () => { ultimo = ""; programar(); requestAnimationFrame(() => requestAnimationFrame(() => { ultimo = ""; medir(); })); };
}

/** Interpolación con suavizado (easeInOutCubic). @param {number} t */
export const suavizar = (t) => (t < 0.5 ? 4 * t * t * t : 1 - ((-2 * t + 2) ** 3) / 2);
