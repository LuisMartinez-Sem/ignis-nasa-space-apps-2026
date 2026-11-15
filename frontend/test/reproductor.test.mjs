import assert from "node:assert/strict";
import test from "node:test";
// reproductor.js importa dom.js (usa document solo dentro de funciones): las funciones puras se importan sin DOM
const { avanzar, desglose, frameEn, VELOCIDADES } = await import("../js/reproductor.js");

test("velocidades permitidas", () => assert.deepEqual(VELOCIDADES, [0.5, 1, 2, 10]));

test("avanzar respeta la velocidad y se detiene al final", () => {
  assert.deepEqual(avanzar(0, 1, 2, 60), { t: 2, terminado: false });
  assert.deepEqual(avanzar(59, 1, 10, 60), { t: 60, terminado: true });
  assert.equal(avanzar(0, 1, 0.5, 60).t, 0.5);
});

test("frameEn acota a los extremos", () => {
  const g = { frames: [{ t_s: 0 }, { t_s: 1 }, { t_s: 2 }] };
  assert.equal(frameEn(g, -5).indice, 0);
  assert.equal(frameEn(g, 1.9).indice, 1);
  assert.equal(frameEn(g, 99).indice, 2);
});

test("desglose de latencia: suma lo medido y marca lo ausente", () => {
  const d = desglose({ muestreo_ms: 100, tcn_ms_medio: 1, tcn_ms_p95: 1.5, modelo_ms_medio: 0.5 }, 9.5);
  assert.equal(d.total, 111);
  const sinDetector = desglose({ muestreo_ms: 100, tcn_ms_medio: null, tcn_ms_p95: null, modelo_ms_medio: null }, null);
  assert.equal(sinDetector.partes[1].ms, null);
  assert.equal(sinDetector.partes[2].ms, null);
  assert.equal(sinDetector.total, 100);
});
