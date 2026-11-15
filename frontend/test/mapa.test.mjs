import test from "node:test";
import assert from "node:assert/strict";
import { colorIndice, nombreNivel, valorEn } from "../js/mapa.js";

test("nombreNivel respeta las fronteras 25/50/75", () => {
  assert.equal(nombreNivel(0), "NOMINAL");
  assert.equal(nombreNivel(24.9), "NOMINAL");
  assert.equal(nombreNivel(25), "PRECAUCIÓN");
  assert.equal(nombreNivel(50), "ALERTA");
  assert.equal(nombreNivel(75), "CRÍTICO");
  assert.equal(nombreNivel(100), "CRÍTICO");
});

test("colorIndice devuelve [r,g,b] en 0-255 y satura fuera de 0-100", () => {
  const c = colorIndice(50);
  assert.equal(c.length, 3);
  assert.ok(c.every((x) => Number.isInteger(x) && x >= 0 && x <= 255));
  assert.deepEqual(colorIndice(-20), colorIndice(0));
  assert.deepEqual(colorIndice(180), colorIndice(100));
});

test("valorEn interpola bilinealmente (valores exactos conocidos)", () => {
  // f(o2, p) = o2 + p sobre 2x2: la interpolación bilineal reproduce exactamente un plano.
  const m = { o2_pct: [0, 10], presion_kpa: [0, 20], indice: [[0, 10], [20, 30]] };
  assert.equal(valorEn(m, 0, 0), 0);
  assert.equal(valorEn(m, 10, 20), 30);
  assert.equal(valorEn(m, 5, 10), 15);
  assert.equal(valorEn(m, 2.5, 5), 7.5);
});

test("valorEn satura fuera del dominio (no extrapola)", () => {
  const m = { o2_pct: [0, 10], presion_kpa: [0, 20], indice: [[0, 10], [20, 30]] };
  assert.equal(valorEn(m, -99, -99), 0);
  assert.equal(valorEn(m, 99, 99), 30);
});
