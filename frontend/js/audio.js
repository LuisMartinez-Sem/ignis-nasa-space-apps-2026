// @ts-check
/**
 * Sonificación con Web Audio: el estado se OYE sin mirar la pantalla.
 * - Zumbido de fondo: más agudo y con trémolo más rápido cuanto mayor es el índice.
 * - Alarma de 3 pulsos cuando el detector temporal dispara o el nivel sube a ALERTA+.
 * - Un tono por sensor (6 canales, acorde mayor con séptima): cada uno suena más fuerte cuanto más se
 *   aleja su canal de la línea base; con peligro la armonía se ROMPE (desafinación hacia segundas menores).
 * - Latido: 60 lpm en NOMINAL → 140 lpm en CRÍTICO.
 * - Voz (Web Speech API) solo para alertas CRÍTICAS.
 * Por política de autoplay del navegador SOLO arranca tras un clic del usuario y
 * está apagado por defecto.
 */

const VOLUMEN_MAESTRO = 0.1;
const ORDEN_NIVEL = { NOMINAL: 0, PRECAUCION: 1, ALERTA: 2, CRITICO: 3 };
/** Un tono por canal de sensor (G3 B3 D4 F#4 A4 C5): consonantes en reposo. */
export const FRECUENCIAS_SENSORES = [196.0, 246.94, 293.66, 369.99, 440.0, 523.25];
/** Desafinación máxima (cents) por voz con peligro 1: segundas menores y tritonos, armonía rota. */
const DESAFINACION_CENTS = [0, 85, -110, 140, -165, 190];
export const BPM_NOMINAL = 60;
export const BPM_CRITICO = 140;
const VOLUMEN_VOCES = 0.5;
const ESPERA_VOZ_MS = 15000;

/** Latidos por minuto según el peligro (0..1), lineal entre 60 y 140. @param {number} peligro */
export function bpmPorPeligro(peligro) {
  const p = Math.min(1, Math.max(0, Number.isFinite(peligro) ? peligro : 0));
  return Math.round(BPM_NOMINAL + (BPM_CRITICO - BPM_NOMINAL) * p);
}

/** Desafinación (cents) de la voz i con peligro 0..1. @param {number} i @param {number} peligro */
export function desafinacion(i, peligro) {
  return DESAFINACION_CENTS[i] * Math.min(1, Math.max(0, peligro));
}

/** Texto apto para voz: sin símbolos que el sintetizador lee mal. @param {string} texto */
export function textoParaVoz(texto) {
  return texto.replace(/CO₂/g, "dióxido de carbono").replace(/O₂/g, "oxígeno").replace(/[⚠\[\]]/g, " ").replace(/\s+/g, " ").trim();
}

export function crearAudio() {
  /** @type {AudioContext|null} */ let ctx = null;
  /** @type {{ base: OscillatorNode, armonico: OscillatorNode, lfo: OscillatorNode, tremolo: GainNode, maestro: GainNode, filtro: BiquadFilterNode }|null} */
  let nodos = null;
  let activo = false;
  /** @type {keyof typeof ORDEN_NIVEL} */ let nivelPrevio = "NOMINAL";
  /** @type {{ osc: OscillatorNode, ganancia: GainNode }[]} */ let voces = [];
  let peligro = 0;
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let latidoTimer;
  let ultimaVoz = 0;

  function construir() {
    const Contexto = window.AudioContext ?? /** @type {any} */ (window).webkitAudioContext;
    if (!Contexto) throw new Error("Web Audio no disponible");
    ctx = new Contexto();
    const maestro = ctx.createGain();
    maestro.gain.value = 0;
    const filtro = ctx.createBiquadFilter();
    filtro.type = "lowpass";
    filtro.frequency.value = 500;
    const tremolo = ctx.createGain();
    tremolo.gain.value = 0.7;
    const base = ctx.createOscillator();
    base.type = "sine";
    base.frequency.value = 55;
    const armonico = ctx.createOscillator();
    armonico.type = "triangle";
    armonico.frequency.value = 110.6; // ligera desafinación: batido lento, aspecto de "máquina"
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 0.5;
    const profundidad = ctx.createGain();
    profundidad.gain.value = 0.3;
    lfo.connect(profundidad).connect(tremolo.gain);
    base.connect(filtro);
    armonico.connect(filtro);
    filtro.connect(tremolo).connect(maestro).connect(ctx.destination);
    for (const o of [base, armonico, lfo]) o.start();
    nodos = { base, armonico, lfo, tremolo, maestro, filtro };
    // Una voz por sensor, suave y en reposo casi inaudible hasta que su canal se mueva
    voces = FRECUENCIAS_SENSORES.map((f) => {
      const osc = /** @type {AudioContext} */ (ctx).createOscillator();
      const ganancia = /** @type {AudioContext} */ (ctx).createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      ganancia.gain.value = 0.02;
      osc.connect(ganancia).connect(maestro);
      osc.start();
      return { osc, ganancia };
    });
  }

  /** Un latido "lub-dub" (dos golpes graves). */
  function latido() {
    if (!ctx || !activo) return;
    for (const [retardo, f, vol] of /** @type {[number, number, number][]} */ ([[0, 62, 1], [0.16, 50, 0.7]])) {
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      const t0 = ctx.currentTime + retardo;
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(VOLUMEN_MAESTRO * 2.2 * vol, t0 + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.14);
      osc.connect(g).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.16);
    }
  }

  function programarLatido() {
    clearTimeout(latidoTimer);
    if (!activo) return;
    latido();
    latidoTimer = setTimeout(programarLatido, 60000 / bpmPorPeligro(peligro));
  }

  /** @param {number} frecuencia @param {number} duracion @param {number} inicio */
  function pulso(frecuencia, duracion, inicio) {
    if (!ctx || !nodos) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = frecuencia;
    const t0 = ctx.currentTime + inicio;
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(VOLUMEN_MAESTRO * 0.8, t0 + 0.01);
    g.gain.setValueAtTime(VOLUMEN_MAESTRO * 0.8, t0 + duracion - 0.02);
    g.gain.linearRampToValueAtTime(0, t0 + duracion);
    osc.connect(g).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + duracion + 0.02);
  }

  return {
    get activo() {
      return activo;
    },

    /**
     * Activa o silencia (llamar desde un gesto del usuario).
     * @param {boolean} encender
     * @returns {Promise<boolean>} estado final
     */
    async fijar(encender) {
      if (encender) {
        try {
          if (!ctx) construir();
          await ctx?.resume();
          nodos?.maestro.gain.setTargetAtTime(VOLUMEN_MAESTRO, ctx?.currentTime ?? 0, 0.2);
          activo = true;
          programarLatido();
        } catch (error) {
          console.error("[IGNIS] Audio no disponible", error);
          activo = false;
        }
      } else {
        nodos?.maestro.gain.setTargetAtTime(0, ctx?.currentTime ?? 0, 0.1);
        activo = false;
        clearTimeout(latidoTimer);
        if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      }
      return activo;
    },

    /**
     * @param {{ indice: number, nivel: keyof typeof ORDEN_NIVEL }} estado
     */
    actualizar({ indice, nivel }) {
      if (!activo || !ctx || !nodos) return;
      const t = ctx.currentTime;
      nodos.base.frequency.setTargetAtTime(55 + indice * 1.1, t, 0.3);
      nodos.armonico.frequency.setTargetAtTime(110.6 + indice * 2.2, t, 0.3);
      nodos.filtro.frequency.setTargetAtTime(380 + indice * 14, t, 0.3);
      nodos.lfo.frequency.setTargetAtTime(0.5 + (indice / 100) * 7, t, 0.3);
      if (ORDEN_NIVEL[nivel] >= 2 && ORDEN_NIVEL[nivelPrevio] < 2) this.alarma();
      nivelPrevio = nivel;
    },

    /**
     * Sonifica los 6 sensores y el peligro global.
     * @param {Record<string, number>|null} canalesNorm canales normalizados (z) del detector
     * @param {number} peligroGlobal 0..1 (índice/100 solo si hay evento)
     */
    sensores(canalesNorm, peligroGlobal) {
      peligro = Math.min(1, Math.max(0, peligroGlobal));
      if (!activo || !ctx || !canalesNorm) return;
      const t = ctx.currentTime;
      Object.values(canalesNorm).slice(0, voces.length).forEach((z, i) => {
        const v = voces[i];
        v.ganancia.gain.setTargetAtTime(0.02 + Math.min(1, Math.abs(z)) * 0.16 * VOLUMEN_VOCES, t, 0.15);
        v.osc.detune.setTargetAtTime(desafinacion(i, peligro), t, 0.25);
      });
    },

    /** Voz para alertas críticas (máx. una cada 15 s). @param {string} texto */
    voz(texto) {
      if (!activo || !("speechSynthesis" in window)) return;
      const ahora = Date.now();
      if (ahora - ultimaVoz < ESPERA_VOZ_MS) return;
      ultimaVoz = ahora;
      window.speechSynthesis.cancel();
      const frase = new SpeechSynthesisUtterance(textoParaVoz(texto));
      frase.lang = "es-MX";
      frase.rate = 1.05;
      frase.volume = 0.9;
      window.speechSynthesis.speak(frase);
    },

    /** Tres pulsos agudos (alarma del detector temporal). */
    alarma() {
      if (!activo) return;
      pulso(880, 0.14, 0);
      pulso(880, 0.14, 0.22);
      pulso(1175, 0.28, 0.44);
    },
  };
}
