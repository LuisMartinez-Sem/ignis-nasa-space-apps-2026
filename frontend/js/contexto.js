// @ts-check
/**
 * Panel «Atmósfera en contexto» del Monitor: sitúa las condiciones actuales frente al aire terrestre, la ISS y el reto lunar.
 * Todo son cálculos directos (sin modelo): pO₂ = fracción de O₂ × presión total. Los umbrales lunares son los del reto NASA 2026.
 */
import { h, obtener } from "./dom.js";

export const PO2_TIERRA_KPA = 21.3;      // 0,21 × 101,325 kPa
export const O2_TIERRA_PCT = 20.95;      // aire seco
export const LUNA_O2_MIN_PCT = 30;       // «probablemente ≥ 30 % de O₂» (reto)
export const LUNA_P_MAX_KPA = 70.3;      // «10,2 psi o menos» (reto)
export const DOMINIO = { o2: [16, 40], presion: [35, 101.325] };  // dominio donde se entrenó el modelo

/**
 * Valores derivados y la región atmosférica. Función pura (probada aparte).
 * @param {{ o2_pct: number, presion_kpa: number }} c
 */
export function contextoAtmosfera(c) {
  const { o2_pct: o2, presion_kpa: p } = c;
  const po2 = (o2 / 100) * p;
  const enriquecimiento = (o2 / O2_TIERRA_PCT - 1) * 100;      // % más O₂ que el aire (en fracción molar)
  const po2Relativa = (po2 / PO2_TIERRA_KPA - 1) * 100;        // % más pO₂ que a nivel del mar
  const fuera = o2 < DOMINIO.o2[0] || o2 > DOMINIO.o2[1] || p < DOMINIO.presion[0] || p > DOMINIO.presion[1];
  /** @type {{ id: "fuera"|"lunar"|"aire"|"intermedia", texto: string }} */
  const region = fuera ? { id: "fuera", texto: "Fuera del dominio del modelo: el índice no es confiable aquí." }
    : o2 >= LUNA_O2_MIN_PCT && p <= LUNA_P_MAX_KPA ? { id: "lunar", texto: "Dentro del rango lunar esperado (≥ 30 % de O₂ y ≤ 70,3 kPa): los materiales arden con más facilidad que en el aire." }
    : Math.abs(o2 - 21) <= 1.5 && p >= 95 ? { id: "aire", texto: "Equivalente al aire de la ISS o de la Tierra." }
    : { id: "intermedia", texto: "Atmósfera intermedia: ni la de la ISS ni la lunar del reto." };
  return { po2_kpa: po2, enriquecimiento_pct: enriquecimiento, po2_relativa_pct: po2Relativa, region };
}

const signo = (/** @type {number} */ v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(0)} %`;

export function crearContexto() {
  const cont = obtener("contexto-cuerpo");
  return {
    /** @param {any} condiciones el campo `condiciones` del mensaje del servidor */
    actualizar(condiciones) {
      if (!condiciones || typeof condiciones.fraccion_o2 !== "number" || typeof condiciones.presion_kpa !== "number") return;
      const x = contextoAtmosfera({ o2_pct: condiciones.fraccion_o2 * 100, presion_kpa: condiciones.presion_kpa });
      const filas = /** @type {[string, string, number][]} */ ([
        ["pO₂ ahora", `${x.po2_kpa.toFixed(1)} kPa`, Math.min(100, (x.po2_kpa / 40) * 100)],
        ["pO₂ aire terrestre", `${PO2_TIERRA_KPA.toFixed(1)} kPa`, (PO2_TIERRA_KPA / 40) * 100],
      ]);
      const barras = h("div", "ctx-barras");
      for (const [k, v, pct] of filas) {
        const f = h("div", "ctx-fila"), b = h("span", "ctx-barra"), r = h("span"); r.style.width = `${pct}%`; b.append(r);
        f.append(h("span", "ctx-k", k), h("strong", "mono", v), b); barras.append(f);
      }
      const datos = h("p", "ctx-datos");
      datos.append(`O₂ ${signo(x.enriquecimiento_pct)} frente al aire · pO₂ ${signo(x.po2_relativa_pct)} frente al nivel del mar`);
      const reg = h("p", "ctx-region", x.region.texto); reg.dataset.region = x.region.id;
      cont.replaceChildren(barras, datos, reg);
    },
  };
}
