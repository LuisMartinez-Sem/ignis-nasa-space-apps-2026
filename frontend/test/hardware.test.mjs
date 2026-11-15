import test from "node:test";
import assert from "node:assert/strict";
import { textoChip } from "../js/hardware.js";

test("textoChip: sin conexión, sin señal y en línea", () => {
  assert.equal(textoChip(null), "Arduino: sin conexión");
  assert.equal(textoChip({ conectado: false, ultimo_dato_s: null }), "Arduino: sin conexión");
  assert.match(textoChip({ conectado: false, ultimo_dato_s: 12.4 }), /sin señal \(12 s\)/);
  assert.equal(textoChip({ conectado: true, ultimo_dato_s: 0.4, lectura: { temperatura_k: 298.15 } }), "Arduino · 25.0 °C");
});
