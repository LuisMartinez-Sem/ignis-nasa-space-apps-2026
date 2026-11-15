// @ts-check
/**
 * Núcleo de anillos concéntricos: firma visual de IGNIS.
 *  - Los anillos pulsan más rápido y más amplio cuanto mayor es el riesgo.
 *  - El arco exterior es el medidor 0–100 (con marcas en 25/50/75).
 *  - Las partículas fluyen hacia afuera con la velocidad de propagación.
 *  - Un anillo punteado cian aparece con la llama fría (invisible en cámara visible).
 */
import { COLOR_NIVEL, VELOCIDAD_NORMALIZACION_MM_S } from "./paleta.js";

const TAU = Math.PI * 2;
const NUM_ANILLOS = 5;
const MAX_PARTICULAS = 240;
const NUM_MARCAS = 54;
const ANGULO_INICIO = Math.PI * 0.75; // abajo-izquierda, como un velocímetro
const BARRIDO = Math.PI * 1.5; // 270°
const CIAN = COLOR_NIVEL.NOMINAL;

/**
 * @typedef {object} EstadoNucleo
 * @property {number} indice Índice de riesgo 0–100.
 * @property {import("./paleta.js").NivelRiesgo} nivel
 * @property {number} velocidad Velocidad de propagación (mm/s).
 * @property {number|null} llamaFria Probabilidad 0–1 o null si no se mide.
 */

export class NucleoAnillos {
  /**
   * @param {HTMLCanvasElement} lienzo
   * @param {{alSuavizar?: (indice: number) => void}} [opciones]
   *   `alSuavizar` recibe el índice interpolado en cada fotograma (para el número del HUD).
   */
  constructor(lienzo, opciones = {}) {
    const contexto = lienzo.getContext("2d");
    if (!contexto) throw new Error("Canvas 2D no disponible");
    this.lienzo = lienzo;
    this.ctx = contexto;
    this.alSuavizar = opciones.alSuavizar;
    /** @type {EstadoNucleo} */
    this.objetivo = { indice: 0, nivel: "NOMINAL", velocidad: 0, llamaFria: null };
    this.mostrado = { indice: 0, color: [...COLOR_NIVEL.NOMINAL], llamaFria: 0, velocidad: 0 };
    this.reducirMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Pool fijo: sin asignaciones por fotograma => sin tirones de GC
    this.particulas = Array.from({ length: MAX_PARTICULAS }, () => ({
      vivo: false, angulo: 0, radio: 0, velocidad: 0, vida: 0, vidaMax: 1,
    }));
    this.acumuladorParticulas = 0;
    this.fase = 0;
    this.rotacion = 0;
    this.ultimoTiempo = 0;
    this.ancho = 0;
    this.alto = 0;
    this.idFotograma = 0;
    this.observador = new ResizeObserver(() => this.#ajustarTamano());
  }

  /** Arranca el bucle de animación. */
  iniciar() {
    this.observador.observe(this.lienzo);
    this.#ajustarTamano();
    this.ultimoTiempo = performance.now();
    const bucle = (/** @type {number} */ ahora) => {
      this.#fotograma(ahora);
      this.idFotograma = requestAnimationFrame(bucle);
    };
    this.idFotograma = requestAnimationFrame(bucle);
  }

  /** Detiene el bucle y la observación de tamaño. */
  detener() {
    cancelAnimationFrame(this.idFotograma);
    this.observador.disconnect();
  }

  /** @param {EstadoNucleo} estado Nuevo objetivo; la vista lo alcanza suavemente. */
  establecer(estado) {
    this.objetivo = estado;
  }

  #ajustarTamano() {
    const caja = this.lienzo.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2); // 2× basta; 3× solo cuesta
    this.lienzo.width = Math.max(1, Math.round(caja.width * dpr));
    this.lienzo.height = Math.max(1, Math.round(caja.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.ancho = caja.width;
    this.alto = caja.height;
  }

  /** @param {number} ahora */
  #fotograma(ahora) {
    const dt = Math.min(0.05, (ahora - this.ultimoTiempo) / 1000);
    this.ultimoTiempo = ahora;

    // Suavizado exponencial independiente del framerate
    const k = 1 - Math.exp(-dt * 4);
    const m = this.mostrado;
    m.indice += (this.objetivo.indice - m.indice) * k;
    m.velocidad += (this.objetivo.velocidad - m.velocidad) * k;
    m.llamaFria += ((this.objetivo.llamaFria ?? 0) - m.llamaFria) * k;
    const destino = COLOR_NIVEL[this.objetivo.nivel];
    for (let i = 0; i < 3; i += 1) m.color[i] += (destino[i] - m.color[i]) * k;

    const riesgo = Math.min(1, Math.max(0, m.indice / 100));
    if (!this.reducirMovimiento) {
      this.fase += dt * TAU * (0.35 + 2.0 * riesgo); // pulso: 0.35 Hz → 2.35 Hz
      this.rotacion += dt * 0.12;
    }
    this.alSuavizar?.(m.indice);
    this.#dibujar(dt, riesgo);
  }

  /**
   * @param {number} dt
   * @param {number} riesgo 0–1
   */
  #dibujar(dt, riesgo) {
    const { ctx, ancho, alto, mostrado } = this;
    ctx.clearRect(0, 0, ancho, alto);
    const cx = ancho / 2;
    const cy = alto / 2;
    const R = (Math.min(ancho, alto) / 2) * 0.96;
    const [r, g, b] = mostrado.color.map(Math.round);
    const rgba = (/** @type {number} */ a) => `rgba(${r},${g},${b},${a})`;

    // Halo: el fondo "se calienta" con el riesgo
    const halo = ctx.createRadialGradient(cx, cy, R * 0.05, cx, cy, R);
    halo.addColorStop(0, rgba(0.1 + 0.22 * riesgo));
    halo.addColorStop(1, rgba(0));
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, ancho, alto);

    // Anillos pulsantes
    const amplitud = this.reducirMovimiento ? 0 : R * 0.012 * (0.6 + 3 * riesgo);
    for (let i = 0; i < NUM_ANILLOS; i += 1) {
      const radio = R * (0.3 + 0.115 * i) + amplitud * Math.sin(this.fase - i * 0.7);
      ctx.beginPath();
      ctx.arc(cx, cy, radio, 0, TAU);
      ctx.lineWidth = 1 + 1.2 * riesgo;
      ctx.strokeStyle = rgba(Math.max(0.12, 0.7 - i * 0.11));
      ctx.stroke();
    }

    this.#dibujarMedidor(cx, cy, R * 0.88, riesgo, rgba);
    this.#dibujarLlamaFria(cx, cy, R);
    this.#dibujarParticulas(dt, cx, cy, R, rgba);

    // Núcleo: el "punto de ignición"
    const radioNucleo = R * (0.035 + 0.03 * riesgo) + (this.reducirMovimiento ? 0 : amplitud * 0.3 * Math.sin(this.fase));
    ctx.beginPath();
    ctx.arc(cx, cy, Math.max(1, radioNucleo), 0, TAU);
    ctx.fillStyle = rgba(0.95);
    ctx.shadowColor = rgba(0.9);
    ctx.shadowBlur = 18;
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  /**
   * Arco 0–100 con marcas; legible de un vistazo.
   * @param {number} cx @param {number} cy @param {number} radio
   * @param {number} riesgo @param {(a: number) => string} rgba
   */
  #dibujarMedidor(cx, cy, radio, riesgo, rgba) {
    const { ctx } = this;
    ctx.lineCap = "butt";
    ctx.lineWidth = 6;
    ctx.strokeStyle = rgba(0.14);
    ctx.beginPath();
    ctx.arc(cx, cy, radio, ANGULO_INICIO, ANGULO_INICIO + BARRIDO);
    ctx.stroke();

    if (riesgo > 0.002) {
      ctx.strokeStyle = rgba(0.95);
      ctx.shadowColor = rgba(0.8);
      ctx.shadowBlur = 14;
      ctx.beginPath();
      ctx.arc(cx, cy, radio, ANGULO_INICIO, ANGULO_INICIO + BARRIDO * riesgo);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    // Fronteras de nivel (25/50/75) sobre la pista
    ctx.strokeStyle = "rgba(230,237,247,0.45)";
    ctx.lineWidth = 2;
    for (const frontera of [0.25, 0.5, 0.75]) {
      const a = ANGULO_INICIO + BARRIDO * frontera;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * (radio - 5), cy + Math.sin(a) * (radio - 5));
      ctx.lineTo(cx + Math.cos(a) * (radio + 5), cy + Math.sin(a) * (radio + 5));
      ctx.stroke();
    }

    // Marcas de escala: las alcanzadas se iluminan
    ctx.lineWidth = 1.5;
    for (let k = 0; k <= NUM_MARCAS; k += 1) {
      const a = ANGULO_INICIO + (BARRIDO * k) / NUM_MARCAS;
      const largo = k % 5 === 0 ? 16 : 10;
      ctx.strokeStyle = k / NUM_MARCAS <= riesgo ? rgba(0.9) : rgba(0.2);
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * (radio + 9), cy + Math.sin(a) * (radio + 9));
      ctx.lineTo(cx + Math.cos(a) * (radio + 9 + largo * 0.6), cy + Math.sin(a) * (radio + 9 + largo * 0.6));
      ctx.stroke();
    }
  }

  /**
   * Anillos punteados cian giratorios: la llama que no se ve.
   * @param {number} cx @param {number} cy @param {number} R
   */
  #dibujarLlamaFria(cx, cy, R) {
    const probabilidad = this.mostrado.llamaFria;
    if (probabilidad < 0.2) return;
    const { ctx } = this;
    const [r, g, b] = CIAN;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.lineWidth = 2;
    ctx.setLineDash([3, 8]);
    ctx.strokeStyle = `rgba(${r},${g},${b},${0.25 + 0.6 * probabilidad})`;
    ctx.rotate(this.rotacion * 2);
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.22, 0, TAU);
    ctx.stroke();
    ctx.rotate(-this.rotacion * 4);
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.18, 0, TAU);
    ctx.stroke();
    ctx.restore();
  }

  /**
   * Partículas radiales: más y más rápidas cuanto más rápida la propagación.
   * @param {number} dt @param {number} cx @param {number} cy @param {number} R
   * @param {(a: number) => string} rgba
   */
  #dibujarParticulas(dt, cx, cy, R, rgba) {
    if (this.reducirMovimiento) return;
    const { ctx } = this;
    const normalizada = Math.min(1, this.mostrado.velocidad / VELOCIDAD_NORMALIZACION_MM_S);

    this.acumuladorParticulas += (3 + 90 * normalizada) * dt;
    while (this.acumuladorParticulas >= 1) {
      this.acumuladorParticulas -= 1;
      const libre = this.particulas.find((p) => !p.vivo);
      if (!libre) break;
      libre.vivo = true;
      libre.angulo = Math.random() * TAU;
      libre.radio = R * 0.1;
      libre.velocidad = R * (0.1 + 0.35 * normalizada) * (0.7 + 0.6 * Math.random());
      libre.vida = 0;
      libre.vidaMax = 1.2 + 1.2 * Math.random();
    }

    for (const p of this.particulas) {
      if (!p.vivo) continue;
      p.vida += dt;
      p.radio += p.velocidad * dt;
      if (p.vida >= p.vidaMax || p.radio > R * 0.8) {
        p.vivo = false;
        continue;
      }
      ctx.fillStyle = rgba((1 - p.vida / p.vidaMax) * 0.9);
      ctx.beginPath();
      ctx.arc(cx + Math.cos(p.angulo) * p.radio, cy + Math.sin(p.angulo) * p.radio, 1.5, 0, TAU);
      ctx.fill();
    }
  }
}
