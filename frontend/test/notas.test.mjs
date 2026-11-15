import test from "node:test";
import assert from "node:assert/strict";
import { leerEstado, sembrar, aTxt, pendientes, TAREAS_INICIALES } from "../js/notas.js";
import { etiqueta, etiquetaValor, etiquetarTexto } from "../js/etiquetas.js";

test("etiquetas: campos y valores legibles", () => {
  assert.equal(etiqueta("areas_seguridad"), "áreas de seguridad");
  assert.equal(etiqueta("datos_en_psi"), "datos en PSI");
  assert.equal(etiqueta("campo_raro_x"), "campo raro x");
  assert.equal(etiquetaValor("prevencion, deteccion"), "prevención, detección");
  assert.equal(etiquetaValor("parcial_pendiente"), "gravedad parcial (pendiente)");
  assert.equal(etiquetarTexto("falta o2_pct y flujo_cm_s"), "falta O₂ y flujo");
});

test("notas: estado corrupto no rompe y se siembra una sola vez", () => {
  assert.deepEqual(leerEstado("{no es json").tareas, []);
  const e = sembrar(leerEstado(null));
  assert.equal(e.tareas.length, TAREAS_INICIALES.length);
  assert.equal(sembrar(e).tareas.length, TAREAS_INICIALES.length);
  assert.equal(pendientes(e), TAREAS_INICIALES.length);
});

test("notas: ida y vuelta y exportación TXT", () => {
  const e = leerEstado(JSON.stringify({ general: "hola", porInv: { a: "nota A", b: "  " }, tareas: [{ id: "1", texto: "T", hecha: true }], sembrado: true }));
  assert.deepEqual(Object.keys(e.porInv), ["a"]);
  const t = aTxt(e, (id) => id.toUpperCase(), "2026-11-12");
  assert.match(t, /\[x\] T/); assert.match(t, /— A:\nnota A/); assert.match(t, /hola/);
});
