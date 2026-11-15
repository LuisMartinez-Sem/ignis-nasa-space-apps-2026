// @ts-check
/** Utilidades mínimas de DOM compartidas por los módulos del HUD. */

/**
 * Obtiene un elemento por id o falla ruidosamente: un id mal escrito en el HTML
 * debe romper en desarrollo, no dejar el HUD "muerto" en silencio.
 * @template {HTMLElement} T
 * @param {string} id
 * @returns {T}
 */
export function obtener(id) {
  const nodo = document.getElementById(id);
  if (!nodo) throw new Error(`[IGNIS] Elemento #${id} no existe en el HTML`);
  return /** @type {T} */ (nodo);
}

/**
 * Crea un elemento con clase y texto seguro (textContent: nunca HTML).
 * @param {string} etiqueta @param {string|null} [clase] @param {string|null} [texto]
 */
export function h(etiqueta, clase = null, texto = null) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== null) nodo.textContent = texto;
  return nodo;
}

/**
 * Crea un elemento SVG con atributos.
 * @param {string} etiqueta @param {Record<string, string|number>} [atributos]
 */
export function s(etiqueta, atributos = {}) {
  const nodo = document.createElementNS("http://www.w3.org/2000/svg", etiqueta);
  for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, String(v));
  return nodo;
}
