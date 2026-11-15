import test from "node:test";
import assert from "node:assert/strict";
import { contextoAtmosfera, PO2_TIERRA_KPA } from "../js/contexto.js";

const casi = (a, b, tol = 0.05) => assert.ok(Math.abs(a - b) <= tol, `${a} ≉ ${b}`);

test("pO₂ = fracción × presión (aire terrestre ≈ 21,3 kPa)", () => {
  casi(contextoAtmosfera({ o2_pct: 21, presion_kpa: 101.325 }).po2_kpa, PO2_TIERRA_KPA, 0.05);
  casi(contextoAtmosfera({ o2_pct: 30, presion_kpa: 70.3 }).po2_kpa, 21.09, 0.01);
});

test("el reto: 30 % de O₂ es más de 40 % de enriquecimiento frente al aire", () => {
  assert.ok(contextoAtmosfera({ o2_pct: 30, presion_kpa: 70.3 }).enriquecimiento_pct > 40);
});

test("la región respeta los umbrales del reto y el dominio del modelo", () => {
  assert.equal(contextoAtmosfera({ o2_pct: 30, presion_kpa: 70.3 }).region.id, "lunar");
  assert.equal(contextoAtmosfera({ o2_pct: 30, presion_kpa: 70.4 }).region.id, "intermedia");   // justo por encima de 10,2 psi
  assert.equal(contextoAtmosfera({ o2_pct: 29.9, presion_kpa: 60 }).region.id, "intermedia");
  assert.equal(contextoAtmosfera({ o2_pct: 21, presion_kpa: 101.3 }).region.id, "aire");
  assert.equal(contextoAtmosfera({ o2_pct: 100, presion_kpa: 29.6 }).region.id, "fuera");        // traje espacial
});
