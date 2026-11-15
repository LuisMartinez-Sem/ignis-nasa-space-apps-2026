import test from "node:test";
import assert from "node:assert/strict";
import { construirPayload } from "../js/cajanegra.js";

test("el payload solo lleva campos del esquema y valores acotados", () => {
  const p = construirPayload({ t_s: 12.3, nivel: "ALERTA", evento: true, alarma: false, escenario: "x".repeat(200),
    evaluacion: { indice_riesgo: 140, probabilidad_propagacion: 0.5, acciones_sugeridas: ["a"], extra_raro: 1 },
    condiciones: { fraccion_o2: 0.25, material: "sibal", otro: 7 }, historial: [{ t_s: 0, indice_riesgo: 10 }] });
  assert.equal(p.indice_riesgo, 100);
  assert.equal(p.escenario.length, 80);
  assert.deepEqual(Object.keys(p.condiciones).sort(), ["fraccion_o2", "material"]);
  assert.equal("extra_raro" in p, false);
  assert.equal(p.historial.length, 1);
});
