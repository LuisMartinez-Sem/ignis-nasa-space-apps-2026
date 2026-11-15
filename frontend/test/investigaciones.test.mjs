import test from "node:test";
import assert from "node:assert/strict";
import { claseNivel, texto } from "../js/investigaciones.js";

test("claseNivel agrupa el puntaje", () => {
  assert.equal(claseNivel(80), "alta");
  assert.equal(claseNivel(50), "media");
  assert.equal(claseNivel(10), "baja");
});

test("texto nunca imprime null ni undefined", () => {
  assert.equal(texto(null), "n/d");
  assert.equal(texto(undefined), "n/d");
  assert.equal(texto(0), "0");
});

import { mejorPorComponente } from "../js/investigaciones.js";
test("mejorPorComponente marca al mayor valor y admite empates", () => {
  const mk = (id, v) => ({ investigacion: { id }, desglose: [{ componente: "o2", valor: v }] });
  const r = mejorPorComponente([mk("a", 0.2), mk("b", 0.9), mk("c", 0.9)]);
  assert.deepEqual([...r.o2].sort(), ["b", "c"]);
});
