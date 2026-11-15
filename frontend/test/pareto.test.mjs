import test from "node:test";
import assert from "node:assert/strict";
import { agrupar, proyector, describirGrupo } from "../js/pareto.js";

const pts = [
  { id: "a", nombre: "A", x: 15, y: 76, capa: 3, en_frontera: false, lectura: "" },
  { id: "b", nombre: "B", x: 15, y: 76, capa: 1, en_frontera: true, lectura: "" },
  { id: "c", nombre: "C", x: 100, y: 66, capa: 6, en_frontera: false, lectura: "" },
];

test("agrupar fusiona posiciones idénticas y conserva la mejor capa y la frontera", () => {
  const g = agrupar(pts);
  assert.equal(g.length, 2);
  const doble = g.find((x) => x.miembros.length === 2);
  assert.equal(doble.capa, 1);
  assert.equal(doble.en_frontera, true);
});

test("proyector mapea esquinas del plano dentro del lienzo", () => {
  const { X, Y } = proyector(900, 400);
  assert.ok(X(0) < X(100) && Y(100) < Y(0));
  assert.ok(X(100) <= 900 && Y(0) <= 400 && X(0) >= 0 && Y(100) >= 0);
});

test("describirGrupo menciona los nombres y la frontera", () => {
  const t = describirGrupo(agrupar(pts)[0]);
  assert.match(t, /A, B/);
  assert.match(t, /frontera de Pareto/);
});

import { mezclar, colorCapa } from "../js/pareto.js";
test("mezclar interpola linealmente", () => {
  assert.equal(mezclar(0, 10, 0), 0);
  assert.equal(mezclar(0, 10, 1), 10);
  assert.equal(mezclar(2, 4, 0.5), 3);
});
test("colorCapa distingue la frontera del resto", () => {
  assert.notEqual(colorCapa(1), colorCapa(4));
  assert.equal(colorCapa(4), colorCapa(9));
});
