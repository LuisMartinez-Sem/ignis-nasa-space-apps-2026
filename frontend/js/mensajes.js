// @ts-check
/**
 * Mensajes estructurados del copiloto (formato fijo, comprobable con pruebas).
 * Lógica pura: sin DOM ni red. Los números salen de la evaluación del modelo y del guion;
 * las únicas constantes propias están declaradas aquí con su motivo.
 */

/** Distancia SUPUESTA al combustible contiguo (m): con ella, tiempo = distancia / velocidad de llama. */
export const DISTANCIA_PROPAGACION_M = 0.1;
/** ΔT mínimo (K) sobre el ambiente para hablar de "evento" y no solo de condiciones propensas. */
export const UMBRAL_REACCION_K = 50;
export const UMBRAL_O2 = 0.36;
export const UMBRAL_PRESION_KPA = 40;

const NOMBRE_VARIABLE = {
  fraccion_o2: "fracción de O₂", velocidad_flujo_cm_s: "velocidad de flujo", presion_kpa: "presión",
  temperatura_ambiente_k: "temperatura ambiente", espesor_combustible_mm: "espesor del combustible",
  temperatura_reaccion_k: "temperatura de reacción",
};
const RECOMENDACION = {
  fraccion_o2: "ventilar sector", velocidad_flujo_cm_s: "reducir la ventilación forzada del sector",
  presion_kpa: "revisar la presión de cabina", temperatura_ambiente_k: "aislar la fuente de calor",
  espesor_combustible_mm: "retirar material combustible del sector", temperatura_reaccion_k: "aislar la fuente de calor",
};

/**
 * Segundos hasta que la llama alcance el combustible contiguo, o null si no hay propagación apreciable.
 * @param {number|null|undefined} velocidadMmS
 * @param {number} [distanciaM]
 * @returns {number|null}
 */
export function tiempoPropagacionS(velocidadMmS, distanciaM = DISTANCIA_PROPAGACION_M) {
  if (typeof velocidadMmS !== "number" || !Number.isFinite(velocidadMmS) || velocidadMmS < 0.05) return null;
  return Math.round(distanciaM / (velocidadMmS / 1000));
}

/**
 * ¿Hay un evento (reacción térmica o alarma del detector)? Sin evento, el índice es solo potencial latente.
 * @param {any} condiciones @param {boolean} alarmaDetector
 */
export function hayEvento(condiciones, alarmaDetector) {
  const tr = condiciones?.temperatura_reaccion_k;
  const ta = condiciones?.temperatura_ambiente_k;
  return !!alarmaDetector || (typeof tr === "number" && typeof ta === "number" && tr - ta >= UMBRAL_REACCION_K);
}

/**
 * Efecto del factor en puntos de índice, en la unidad que se le muestra al operador.
 * El servidor entrega puntos por cada +10 % RELATIVO de la variable; para O₂ se convierte a +1 punto porcentual.
 * @param {{variable: string, efecto_indice: number}} factor @param {any} condiciones
 * @returns {{ pts: number, unidad: string }}
 */
export function efectoPorUnidad(factor, condiciones) {
  if (factor.variable === "fraccion_o2") {
    const o2Pct = Number(condiciones?.fraccion_o2) * 100;
    if (Number.isFinite(o2Pct) && o2Pct > 0) return { pts: factor.efecto_indice / (0.1 * o2Pct), unidad: "+1%" };
  }
  return { pts: factor.efecto_indice, unidad: "+10%" };
}

/** @param {number} pts */
const signo = (pts) => `${pts >= 0 ? "+" : "−"}${Math.abs(pts).toFixed(1)}`;

/**
 * @typedef {{ tipo: "critico"|"factor"|"llama_fria"|"extrapolacion", severidad: "critica"|"alta"|"media", texto: string, nota?: string }} MensajeCopiloto
 * @typedef {{
 *   nivel: string, evento: boolean, evaluacion: any, condiciones: any,
 *   fuego?: { sector: string, x_m: number, y_m: number, nota?: string } | null,
 *   factores?: any[]
 * }} EntradaMensajes
 */

/**
 * Construye los mensajes del copiloto para el estado actual.
 * @param {EntradaMensajes} entrada
 * @returns {MensajeCopiloto[]}
 */
export function construirMensajes({ nivel, evento, evaluacion, condiciones, fuego, factores }) {
  /** @type {MensajeCopiloto[]} */ const salida = [];
  const e = evaluacion ?? {};
  const c = condiciones ?? {};

  if (evento && nivel === "CRITICO") {
    const sector = fuego?.sector ?? "B-2";
    const x = (fuego?.x_m ?? 1.2).toFixed(1), y = (fuego?.y_m ?? 0.8).toFixed(1);
    const t = tiempoPropagacionS(e.velocidad_propagacion_mm_s);
    const tiempo = t === null ? "sin propagación apreciable" : `${t}s`;
    salida.push({
      tipo: "critico", severidad: "critica",
      texto: `ALERTA CRÍTICA. Foco en sector ${sector}. Coordenadas [${x}, ${y}]. Tiempo estimado antes de propagación: ${tiempo}. Acción: activar supresión CO₂. Confirmar.`,
      nota: `Posición simulada del guion; tiempo = ${DISTANCIA_PROPAGACION_M * 100} cm de combustible contiguo (supuesto) ÷ velocidad de llama del modelo.`,
    });
  }

  const dominante = (factores ?? []).find((f) => f.direccion !== "neutro" && f.efecto_indice > 0);
  if (evento && dominante && (nivel === "CRITICO" || nivel === "ALERTA")) {
    const { pts, unidad } = efectoPorUnidad(dominante, c);
    const umbral = nivel === "CRITICO" ? "Umbral crítico alcanzado." : "Umbral crítico próximo.";
    const nombre = /** @type {Record<string,string>} */ (NOMBRE_VARIABLE)[dominante.variable] ?? dominante.variable;
    const accion = /** @type {Record<string,string>} */ (RECOMENDACION)[dominante.variable] ?? "revisar el sector";
    salida.push({ tipo: "factor", severidad: nivel === "CRITICO" ? "alta" : "media",
      texto: `Factor dominante: ${nombre} (${signo(pts)} pts por cada ${unidad}). ${umbral} Recomendación: ${accion}.` });
  }

  if ((e.estado_llama_fria === "POSIBLE" || e.estado_llama_fria === "PROBABLE") && typeof c.temperatura_reaccion_k === "number") {
    salida.push({ tipo: "llama_fria", severidad: "alta",
      texto: `ADVERTENCIA: Patrón térmico compatible con Cool Flame. Temperatura: ${Math.round(c.temperatura_reaccion_k)} K. Invisible a cámara visible. Confirmar con termografía IR. Puede reavivar en <5 min.` });
  }

  /** @type {string[]} */ const motivos = [];
  if (Number(c.fraccion_o2) > UMBRAL_O2) motivos.push(`O₂ > ${UMBRAL_O2.toFixed(2)}`);
  if (Number(c.presion_kpa) < UMBRAL_PRESION_KPA) motivos.push(`presión < ${UMBRAL_PRESION_KPA} kPa`);
  if (e.fuera_de_dominio && motivos.length === 0) motivos.push("fuera del rango de entrenamiento");
  if (motivos.length) {
    salida.push({ tipo: "extrapolacion", severidad: "media",
      texto: `⚠ Entrada fuera de dominio operativo (${motivos.join(", ")}). Confianza reducida. Interpretar con precaución.` });
  }
  return salida;
}
