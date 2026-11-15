// Pruebas de la lógica pura del copiloto: node --test frontend/test
import assert from "node:assert/strict";
import test from "node:test";
import { construirMensajes, efectoPorUnidad, hayEvento, tiempoPropagacionS } from "../js/mensajes.js";

const cond = { fraccion_o2: 0.21, presion_kpa: 101.3, temperatura_ambiente_k: 295, temperatura_reaccion_k: 680 };

test("tiempo de propagación: 0,1 m ÷ velocidad; sin propagación → null", () => {
  assert.equal(tiempoPropagacionS(2.2), 45);
  assert.equal(tiempoPropagacionS(0.01), null);
  assert.equal(tiempoPropagacionS(null), null);
});

test("hay evento por reacción térmica o por alarma", () => {
  assert.equal(hayEvento({ temperatura_ambiente_k: 295, temperatura_reaccion_k: 296 }, false), false);
  assert.equal(hayEvento(cond, false), true);
  assert.equal(hayEvento({ temperatura_ambiente_k: 295, temperatura_reaccion_k: null }, true), true);
});

test("mensaje CRÍTICO con el formato exacto", () => {
  const m = construirMensajes({ nivel: "CRITICO", evento: true, evaluacion: { velocidad_propagacion_mm_s: 2.2 },
    condiciones: cond, fuego: { sector: "B-2", x_m: 1.2, y_m: 0.8 } });
  assert.equal(m[0].texto, "ALERTA CRÍTICA. Foco en sector B-2. Coordenadas [1.2, 0.8]. Tiempo estimado antes de propagación: 45s. Acción: activar supresión CO₂. Confirmar.");
  assert.equal(m[0].severidad, "critica");
});

test("sin evento no hay alerta crítica aunque el índice latente sea alto", () => {
  assert.equal(construirMensajes({ nivel: "CRITICO", evento: false, evaluacion: {}, condiciones: cond }).length, 0);
});

test("factor dominante: O₂ se expresa por +1 punto porcentual", () => {
  const f = { variable: "fraccion_o2", direccion: "sube", efecto_indice: 5.67 }; // por +10 % relativo (2,1 pp)
  assert.equal(efectoPorUnidad(f, cond).unidad, "+1%");
  assert.ok(Math.abs(efectoPorUnidad(f, cond).pts - 2.7) < 1e-9);
  const m = construirMensajes({ nivel: "CRITICO", evento: true, evaluacion: {}, condiciones: cond, factores: [f] });
  assert.equal(m[1].texto, "Factor dominante: fracción de O₂ (+2.7 pts por cada +1%). Umbral crítico alcanzado. Recomendación: ventilar sector.");
});

test("llama fría: advertencia con temperatura", () => {
  const m = construirMensajes({ nivel: "PRECAUCION", evento: true, evaluacion: { estado_llama_fria: "POSIBLE" }, condiciones: cond });
  assert.equal(m[0].texto, "ADVERTENCIA: Patrón térmico compatible con Cool Flame. Temperatura: 680 K. Invisible a cámara visible. Confirmar con termografía IR. Puede reavivar en <5 min.");
});

test("extrapolación por O₂ alto, por presión baja y por bandera del modelo", () => {
  const dom = (c, e = {}) => construirMensajes({ nivel: "NOMINAL", evento: false, evaluacion: e, condiciones: c })[0]?.texto;
  assert.equal(dom({ fraccion_o2: 0.38, presion_kpa: 101 }), "⚠ Entrada fuera de dominio operativo (O₂ > 0.36). Confianza reducida. Interpretar con precaución.");
  assert.match(dom({ fraccion_o2: 0.21, presion_kpa: 38 }), /presión < 40 kPa/);
  assert.match(dom({ fraccion_o2: 0.21, presion_kpa: 101 }, { fuera_de_dominio: true }), /fuera del rango de entrenamiento/);
  assert.equal(dom({ fraccion_o2: 0.21, presion_kpa: 101 }), undefined);
});
