// @ts-check
/** Controles del simulador: selector de modo y sliders del modo manual. */
import { obtener } from "./dom.js";

const RETARDO_ENVIO_MS = 100; // límite ~10 mensajes/s al arrastrar un slider

/**
 * @typedef {"escenario"|"manual"} Modo
 * @param {{
 *   alCambiarModo: (modo: Modo) => void,
 *   alCambiarCondiciones: (condiciones: object) => void,
 * }} devoluciones
 */
export function crearControles({ alCambiarModo, alCambiarCondiciones }) {
  const botones = /** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-modo]"));
  const panelManual = obtener("panel-manual");
  const o2 = /** @type {HTMLInputElement} */ (obtener("ctl-o2"));
  const flujo = /** @type {HTMLInputElement} */ (obtener("ctl-flujo"));
  const presion = /** @type {HTMLInputElement} */ (obtener("ctl-presion"));
  const temperatura = /** @type {HTMLInputElement} */ (obtener("ctl-temp"));
  const termopar = /** @type {HTMLInputElement} */ (obtener("ctl-termopar"));
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let pendiente;

  /** Condiciones completas (contrato de la API) a partir de los sliders. */
  function condiciones() {
    return {
      fraccion_o2: Number(o2.value) / 100,
      velocidad_flujo_cm_s: Number(flujo.value),
      presion_kpa: Number(presion.value),
      temperatura_ambiente_k: 295,
      espesor_combustible_mm: 0.2,
      material: "sibal",
      temperatura_reaccion_k: termopar.checked ? Number(temperatura.value) : null,
    };
  }

  function refrescarEtiquetas() {
    obtener("ctl-o2-valor").textContent = `${Number(o2.value).toFixed(1)} %`;
    obtener("ctl-flujo-valor").textContent = `${flujo.value} cm/s`;
    obtener("ctl-presion-valor").textContent = `${Number(presion.value).toFixed(1)} kPa`;
    obtener("ctl-temp-valor").textContent = termopar.checked ? `${temperatura.value} K` : "sin sensor";
    temperatura.disabled = !termopar.checked;
  }

  // Trailing throttle: se envía siempre el último valor, sin inundar el servidor
  function programarEnvio() {
    refrescarEtiquetas();
    if (pendiente !== undefined) return;
    pendiente = setTimeout(() => {
      pendiente = undefined;
      alCambiarCondiciones(condiciones());
    }, RETARDO_ENVIO_MS);
  }

  for (const entrada of [o2, flujo, presion, temperatura, termopar]) {
    entrada.addEventListener("input", programarEnvio);
  }

  /** @param {Modo} modo */
  function establecerModo(modo) {
    for (const boton of botones) boton.setAttribute("aria-pressed", String(boton.dataset.modo === modo));
    panelManual.hidden = modo !== "manual";
    refrescarEtiquetas();
    alCambiarModo(modo);
  }

  for (const boton of botones) {
    boton.addEventListener("click", () => establecerModo(/** @type {Modo} */ (boton.dataset.modo)));
  }

  /**
   * Inyecta valores en los sliders (ids de slider → valor en sus unidades) y notifica una vez.
   * @param {Record<string, number|boolean>} valores
   */
  function aplicar(valores) {
    /** @type {Record<string, HTMLInputElement>} */
    const campos = { "ctl-o2": o2, "ctl-flujo": flujo, "ctl-presion": presion, "ctl-temp": temperatura };
    for (const [id, valor] of Object.entries(valores)) {
      if (id === "ctl-termopar") termopar.checked = !!valor;
      else if (campos[id] && typeof valor === "number") campos[id].value = String(Math.min(Number(campos[id].max), Math.max(Number(campos[id].min), valor)));
    }
    refrescarEtiquetas();
    alCambiarCondiciones(condiciones());
  }

  return { establecerModo, condiciones, aplicar };
}
