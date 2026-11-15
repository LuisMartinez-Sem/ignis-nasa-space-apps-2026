// @ts-check
/**
 * Caja Negra: descarga el PDF del estado ACTUAL del simulador (POST /api/v1/incidentes/reporte_pdf_live).
 * Guarda un historial acotado del índice y el último estado; el servidor no re-verifica lo que se envía.
 */

const MAX_HISTORIAL = 600;
const RUTA = "/api/v1/incidentes/reporte_pdf_live";
const CLAVES_CONDICIONES = ["fraccion_o2", "velocidad_flujo_cm_s", "presion_kpa", "temperatura_ambiente_k", "espesor_combustible_mm",
  "material", "regimen_flujo", "temperatura_reaccion_k"];

/** @param {unknown} v @returns {number|null} */
const numero = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/**
 * Construye el cuerpo que el esquema `EstadoVivo` acepta (sin campos extra).
 * @param {{ t_s: number|null, evaluacion: any, condiciones: any, nivel: string, evento: boolean, alarma: boolean,
 *           escenario?: string, historial: { t_s: number, indice_riesgo: number }[] }} e
 */
export function construirPayload(e) {
  const ev = e.evaluacion ?? {};
  /** @type {Record<string, number|string|null>} */ const condiciones = {};
  for (const k of CLAVES_CONDICIONES) {
    const v = e.condiciones?.[k];
    if (typeof v === "string" || numero(v) !== null) condiciones[k] = v;
  }
  const limitar = (/** @type {number|null} */ x, /** @type {number} */ max) => (x === null ? null : Math.min(max, Math.max(0, x)));
  return {
    escenario: (e.escenario || "Monitor en vivo").slice(0, 80),
    t_s: limitar(e.t_s, 1e6),
    indice_riesgo: limitar(numero(ev.indice_riesgo), 100),
    nivel_riesgo: e.nivel ? String(e.nivel).slice(0, 20) : null,
    velocidad_propagacion_mm_s: limitar(numero(ev.velocidad_propagacion_mm_s), 1000),
    probabilidad_propagacion: limitar(numero(ev.probabilidad_propagacion), 1),
    probabilidad_llama_fria: limitar(numero(ev.probabilidad_llama_fria), 1),
    estado_llama_fria: ev.estado_llama_fria ? String(ev.estado_llama_fria).slice(0, 30) : null,
    alarma_detector: !!e.alarma,
    evento_activo: !!e.evento,
    fuera_de_dominio: !!ev.fuera_de_dominio,
    condiciones,
    acciones_sugeridas: (Array.isArray(ev.acciones_sugeridas) ? ev.acciones_sugeridas : []).slice(0, 20).map((/** @type {any} */ a) => String(a).slice(0, 300)),
    advertencias: (Array.isArray(ev.advertencias) ? ev.advertencias : []).slice(0, 20).map((/** @type {any} */ a) => String(a).slice(0, 300)),
    historial: e.historial.slice(-MAX_HISTORIAL),
  };
}

/**
 * @param {{ boton: HTMLButtonElement, fetchFn?: typeof fetch }} opciones
 */
export function crearCajaNegra({ boton, fetchFn = fetch.bind(globalThis) }) {
  /** @type {{ t_s: number, indice_riesgo: number }[]} */ const historial = [];
  /** @type {any} */ let ultimo = null;
  const inicio = performance.now();
  const textoOriginal = boton.textContent ?? "Caja negra";

  async function descargar() {
    if (!ultimo) { boton.textContent = "Sin datos aún"; setTimeout(() => (boton.textContent = textoOriginal), 1800); return; }
    boton.disabled = true;
    boton.textContent = "Generando…";
    try {
      const r = await fetchFn(RUTA, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(construirPayload({ ...ultimo, historial })) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a");
      a.href = url; a.download = "ignis_caja_negra.pdf";
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      boton.textContent = textoOriginal;
    } catch (error) {
      console.error("[IGNIS] No se pudo descargar la caja negra", error);
      boton.textContent = "Error: reintentar";
      setTimeout(() => (boton.textContent = textoOriginal), 2500);
    } finally {
      boton.disabled = false;
    }
  }
  boton.addEventListener("click", descargar);

  return {
    /** Registra el estado actual (llamar en cada evaluación). @param {any} estado */
    registrar(estado) {
      const t = numero(estado.t_s) ?? (performance.now() - inicio) / 1000;
      ultimo = { ...estado, t_s: t };
      const indice = numero(estado.evaluacion?.indice_riesgo);
      if (indice !== null && !estado.sinModelo) {
        historial.push({ t_s: Math.round(t * 10) / 10, indice_riesgo: Math.min(100, Math.max(0, indice)) });
        if (historial.length > MAX_HISTORIAL) historial.shift();
      }
    },
    /** Vacía el historial al cambiar de escenario. */
    reiniciar() { historial.length = 0; },
    descargar,
  };
}
