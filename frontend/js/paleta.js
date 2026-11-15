// @ts-check
/**
 * Paleta y textos por nivel de riesgo: única fuente para el canvas y el HUD.
 * Los RGB replican las variables CSS (--cian, --ambar, --naranja, --rojo).
 */

/** @typedef {"NOMINAL"|"PRECAUCION"|"ALERTA"|"CRITICO"} NivelRiesgo */

/** @type {Record<NivelRiesgo, [number, number, number]>} */
export const COLOR_NIVEL = {
  NOMINAL: [79, 209, 255],
  PRECAUCION: [255, 179, 71],
  ALERTA: [255, 122, 60],
  CRITICO: [255, 59, 59],
};

/** @type {Record<NivelRiesgo, string>} */
export const TEXTO_NIVEL = {
  NOMINAL: "NOMINAL",
  PRECAUCION: "PRECAUCIÓN",
  ALERTA: "ALERTA",
  CRITICO: "CRÍTICO",
};

/** Velocidad (mm/s) que equivale a "llama al 100 %"; debe coincidir con el backend. */
export const VELOCIDAD_NORMALIZACION_MM_S = 4.74;

/**
 * Devuelve el nivel si es válido; si no, NOMINAL (entrada del servidor no confiable).
 * @param {unknown} nivel
 * @returns {NivelRiesgo}
 */
export function normalizarNivel(nivel) {
  return typeof nivel === "string" && Object.hasOwn(COLOR_NIVEL, nivel)
    ? /** @type {NivelRiesgo} */ (nivel)
    : "NOMINAL";
}
