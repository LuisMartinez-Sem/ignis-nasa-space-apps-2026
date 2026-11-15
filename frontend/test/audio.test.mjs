import assert from "node:assert/strict";
import test from "node:test";
import { BPM_CRITICO, BPM_NOMINAL, bpmPorPeligro, desafinacion, FRECUENCIAS_SENSORES, textoParaVoz } from "../js/audio.js";

test("latido: 60 lpm en NOMINAL, 140 en CRÍTICO, acotado", () => {
  assert.equal(bpmPorPeligro(0), BPM_NOMINAL);
  assert.equal(bpmPorPeligro(1), BPM_CRITICO);
  assert.equal(bpmPorPeligro(0.5), 100);
  assert.equal(bpmPorPeligro(9), 140);
  assert.equal(bpmPorPeligro(Number.NaN), 60);
});

test("seis tonos, uno por sensor, y armonía afinada en reposo", () => {
  assert.equal(FRECUENCIAS_SENSORES.length, 6);
  for (let i = 0; i < 6; i++) assert.equal(desafinacion(i, 0) === 0, true);
});

test("con peligro la armonía se rompe (desafinación creciente)", () => {
  assert.ok(Math.abs(desafinacion(5, 1)) > Math.abs(desafinacion(5, 0.3)));
  assert.equal(desafinacion(0, 1), 0); // la voz fundamental no se mueve
});

test("texto de voz sin símbolos problemáticos", () => {
  assert.equal(textoParaVoz("⚠ Activar supresión CO₂ [B-2]"), "Activar supresión dióxido de carbono B-2");
});
