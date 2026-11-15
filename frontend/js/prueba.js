// @ts-check
/**
 * Panel «Datos de prueba»: ensaya cómo entran datos nuevos (CSV) sin tocar el catálogo real.
 * Todo lo que entra queda marcado como PRUEBA y se puede quitar con un clic. Todo texto del servidor entra con textContent.
 */
import { h, obtener } from "./dom.js";

const API = "/api/v1/investigaciones";
const NOMBRE_CAMPO = /** @type {Record<string, string>} */ ({
  investigacion: "nombre de la investigación", objetivos: "objetivos", combustible_detalle: "combustible", hardware: "hardware",
  instalacion: "instalación", o2: "O₂", flujo: "flujo", presion: "presión",
});

/**
 * Líneas legibles del informe de importación (función pura, probada aparte).
 * @param {any} inf
 * @returns {{ texto: string, tipo: "ok"|"aviso"|"error" }[]}
 */
export function resumenInforme(inf) {
  /** @type {{ texto: string, tipo: "ok"|"aviso"|"error" }[]} */
  const l = [];
  if (!inf || typeof inf !== "object") return [{ texto: "Respuesta vacía del servidor.", tipo: "error" }];
  if (inf.estado !== "ok") l.push({ texto: `Se leyeron ${inf.filas} filas pero ninguna coincidió con una investigación: revisa la columna de nombres.`, tipo: "aviso" });
  else l.push({ texto: `Se leyeron ${inf.filas} filas: ${inf.investigaciones_nuevas.length} investigación(es) nueva(s) y ${inf.investigaciones_actualizadas.length} actualizada(s).`, tipo: "ok" });
  const rec = Object.entries(inf.columnas_reconocidas ?? {}).map(([c, f]) => `«${c}» → ${NOMBRE_CAMPO[/** @type {string} */ (f)] ?? f}`);
  if (rec.length) l.push({ texto: `Columnas entendidas: ${rec.join(" · ")}.`, tipo: "ok" });
  if (inf.columnas_ignoradas?.length) l.push({ texto: `Columnas ignoradas (no se adivinan): ${inf.columnas_ignoradas.join(", ")}.`, tipo: "aviso" });
  for (const o of inf.omitidas ?? []) l.push({ texto: `Valor omitido: ${o}.`, tipo: "aviso" });
  for (const c of inf.conflictos ?? []) l.push({ texto: `Conflicto con el catálogo: ${c}.`, tipo: "aviso" });
  for (const n of inf.no_mapeadas ?? []) l.push({ texto: `Sin identificar: «${n}».`, tipo: "aviso" });
  return l;
}

/**
 * @param {{ alCambiar: (informe: any|null) => void | Promise<void> }} o
 */
export function crearPrueba(o) {
  const panel = obtener("inv-prueba-panel"), boton = obtener("inv-prueba-boton"), banner = obtener("inv-prueba-banner"), informe = obtener("inv-prueba-informe");
  const archivo = /** @type {HTMLInputElement} */ (obtener("inv-prueba-archivo"));
  const quitar = /** @type {HTMLButtonElement} */ (obtener("inv-prueba-quitar"));
  let activos = 0;

  /** @param {{ texto: string, tipo: string }[]} lineas */
  function mostrar(lineas) {
    informe.replaceChildren(...lineas.map((x) => { const p = h("p", `prueba-linea prueba-${x.tipo}`, x.texto); return p; }));
  }

  /** @param {string} contenido */
  async function enviar(contenido) {
    mostrar([{ texto: "Procesando…", tipo: "aviso" }]);
    try {
      const r = await fetch(`${API}/prueba`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contenido }) });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        mostrar([{ texto: `No se pudo importar: ${typeof d.detail === "string" ? d.detail : `error ${r.status}`}`, tipo: "error" }]);
        return;
      }
      const inf = await r.json();
      mostrar(resumenInforme(inf));
      await o.alCambiar(inf);
    } catch (error) {
      console.error("[IGNIS] importar prueba", error);
      mostrar([{ texto: "No se pudo contactar con el servidor.", tipo: "error" }]);
    }
  }

  async function cargarEjemplo() {
    const r = await fetch(`${API}/prueba/plantilla`);
    if (!r.ok) { mostrar([{ texto: "No se pudo obtener el ejemplo.", tipo: "error" }]); return; }
    await enviar(await r.text());
  }

  async function quitarPrueba() {
    try {
      const r = await fetch(`${API}/prueba`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      mostrar([{ texto: "Datos de prueba quitados: el catálogo volvió a su estado real.", tipo: "ok" }]);
      await o.alCambiar(null);
    } catch (error) {
      console.error("[IGNIS] quitar prueba", error);
      mostrar([{ texto: "No se pudieron quitar los datos de prueba.", tipo: "error" }]);
    }
  }

  boton.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    boton.setAttribute("aria-expanded", String(!panel.hidden));
  });
  obtener("inv-prueba-ejemplo").addEventListener("click", cargarEjemplo);
  obtener("inv-prueba-subir").addEventListener("click", () => archivo.click());
  archivo.addEventListener("change", async () => {
    const f = archivo.files?.[0];
    archivo.value = "";
    if (!f) return;
    if (f.size > 512_000) { mostrar([{ texto: "El archivo supera 500 KB: para ensayar bastan unas pocas filas.", tipo: "error" }]); return; }
    await enviar(await f.text());
  });
  quitar.addEventListener("click", quitarPrueba);
  obtener("inv-prueba-banner-quitar").addEventListener("click", quitarPrueba);

  return {
    /** Refleja el estado del catálogo: banner permanente mientras haya datos de prueba. @param {string[]} ids */
    mostrarEstado(ids) {
      activos = ids.length;
      banner.hidden = activos === 0;
      quitar.disabled = activos === 0;
      obtener("inv-prueba-banner-texto").textContent = `MODO PRUEBA · ${activos} investigación(es) con datos de prueba (no son datos de la NASA)`;
      boton.dataset.activo = String(activos > 0);
    },
    cargarEjemplo, quitarPrueba,
    abrir() { panel.hidden = false; boton.setAttribute("aria-expanded", "true"); },
    get activos() { return activos; },
  };
}
