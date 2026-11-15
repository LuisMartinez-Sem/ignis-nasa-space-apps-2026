// @ts-check
/** Nombres legibles para los campos y valores técnicos (snake_case) que el servidor devuelve. Solo presentación: no cambia datos. */

/** @type {Record<string, string>} */
export const CAMPOS = {
  o2_pct: "O₂", o2: "O₂", presion_kpa: "presión", presion: "presión", flujo_cm_s: "flujo", flujo: "flujo",
  datos_en_psi: "datos en PSI", datos_psi: "datos en PSI", areas_seguridad: "áreas de seguridad", combustible_tipos: "tipos de combustible",
  campos_no_verificados: "campos sin verificar", familia: "familia", combustible: "combustible", hardware: "hardware", instalacion: "instalación",
  gravedad: "gravedad", fuente: "fuente", objetivos: "objetivos", nombre: "nombre",
};

/** @type {Record<string, string>} */
export const VALORES = {
  solidos: "sólidos", solido: "sólido", gotas: "gotas", gota: "gota", gases: "gases", mezcla: "mezcla", microgravedad: "microgravedad",
  parcial_pendiente: "gravedad parcial (pendiente)", parcial_emulada: "gravedad parcial (emulada)", desconocida: "desconocida", desconocido: "desconocido",
  prevencion: "prevención", deteccion: "detección", supresion: "supresión", extincion: "extinción",
};

/** @param {string} k */
export const etiqueta = (k) => CAMPOS[k] ?? k.replaceAll("_", " ");

/** Valor legible: traduce cada elemento de una lista «a, b». @param {any} v */
export function etiquetaValor(v) {
  if (typeof v !== "string") return v;
  return v.split(", ").map((x) => VALORES[x] ?? (/^[a-z]+(_[a-z]+)+$/.test(x) ? x.replaceAll("_", " ") : x)).join(", ");
}

const RE_CAMPOS = new RegExp(`\\b(${Object.keys(CAMPOS).filter((k) => k.includes("_")).join("|")})\\b`, "g");
/** Sustituye nombres de campo con guion bajo dentro de un texto libre del servidor. @param {string} t */
export const etiquetarTexto = (t) => String(t).replace(RE_CAMPOS, (m) => CAMPOS[m]);
