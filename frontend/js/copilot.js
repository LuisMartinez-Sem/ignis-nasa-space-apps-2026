// @ts-check
/**
 * Copiloto: explica POR QUÉ el riesgo es el que es y compara los motores.
 * Consulta la API REST con límite de frecuencia (el WebSocket manda a 2 Hz; la
 * explicación no necesita ir tan rápido) y cancela peticiones obsoletas.
 * Todo texto del servidor entra con textContent.
 */
import { obtener } from "./dom.js";

const INTERVALO_MS = 1200;
const NOMBRES = {
  fraccion_o2: "O₂",
  velocidad_flujo_cm_s: "flujo de aire",
  presion_kpa: "presión",
  temperatura_ambiente_k: "T ambiente",
  espesor_combustible_mm: "espesor del combustible",
  temperatura_reaccion_k: "T de reacción",
};

/** @param {unknown} v @param {number} d */
const num = (v, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—");

export function crearCopiloto() {
  const selector = /** @type {HTMLSelectElement} */ (obtener("copiloto-motor"));
  const resumen = obtener("copiloto-resumen");
  const lista = obtener("copiloto-factores");
  const comparativa = obtener("copiloto-motores");
  const avisos = obtener("copiloto-avisos");
  const mensajes = obtener("copiloto-mensajes");
  /** @type {any[]} */ let ultimosFactores = [];
  /** @type {AbortController|null} */ let abortador = null;
  let ultimoEnvio = 0;
  /** @type {object|null} */ let pendiente = null;
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let temporizador;
  let motores = ["rf"];

  /** Pregunta qué motores hay listos (el profundo puede estar aún entrenando). */
  async function refrescarMotores() {
    try {
      const r = await fetch("/api/v1/modelo/estado");
      if (!r.ok) return;
      motores = (await r.json()).motores ?? ["rf"];
      for (const opcion of selector.options) opcion.disabled = !motores.includes(opcion.value);
      if (!motores.includes(selector.value)) selector.value = "rf";
    } catch {
      /* sin red: se conserva el estado anterior */
    }
  }
  refrescarMotores();
  setInterval(refrescarMotores, 8000);
  selector.addEventListener("change", () => pendiente && ejecutar(pendiente));

  /**
   * @param {string} motor @param {object} condiciones @param {boolean} explicar @param {AbortSignal} signal
   */
  async function predecir(motor, condiciones, explicar, signal) {
    const r = await fetch(`/api/v1/predict?motor=${motor}&explicar=${explicar}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(condiciones), signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  /** @param {object} condiciones */
  async function ejecutar(condiciones) {
    abortador?.abort();
    abortador = new AbortController();
    const { signal } = abortador;
    ultimoEnvio = Date.now();
    const elegido = motores.includes(selector.value) ? selector.value : "rf";
    const otro = elegido === "rf" ? "profundo" : "rf";
    try {
      const [principal, secundario] = await Promise.all([
        predecir(elegido, condiciones, true, signal),
        motores.includes(otro) ? predecir(otro, condiciones, false, signal) : Promise.resolve(null),
      ]);
      pintar(elegido, principal, otro, secundario);
    } catch (error) {
      if (/** @type {Error} */ (error).name !== "AbortError") resumen.textContent = "No se pudo obtener la explicación.";
    }
  }

  /**
   * @param {string} motor @param {any} p @param {string} otroMotor @param {any} s
   */
  function pintar(motor, p, otroMotor, s) {
    const factores = Array.isArray(p.factores) ? p.factores : [];
    ultimosFactores = factores;
    const principal = factores.find((/** @type {any} */ f) => f.direccion !== "neutro");
    resumen.textContent = principal
      ? `Lo que más mueve el riesgo ahora: ${NOMBRES[principal.variable] ?? principal.variable} ` +
        `(${principal.efecto_indice > 0 ? "+" : ""}${num(principal.efecto_indice, 1)} pts por cada +10 %).`
      : "Ninguna variable domina el riesgo en este momento.";

    const maximo = Math.max(1, ...factores.map((/** @type {any} */ f) => Math.abs(f.efecto_indice)));
    lista.replaceChildren(
      ...factores.slice(0, 5).map((/** @type {any} */ f) => {
        const li = document.createElement("li");
        li.className = "factor";
        li.dataset.direccion = f.direccion;
        const nombre = document.createElement("span");
        nombre.textContent = NOMBRES[f.variable] ?? f.variable;
        const barra = document.createElement("span");
        barra.className = "factor-barra";
        const relleno = document.createElement("span");
        relleno.style.width = `${(Math.abs(f.efecto_indice) / maximo) * 100}%`;
        barra.append(relleno);
        const valor = document.createElement("span");
        valor.className = "mono";
        valor.textContent = `${f.efecto_indice > 0 ? "+" : ""}${num(f.efecto_indice, 1)}`;
        li.append(nombre, barra, valor);
        return li;
      }),
    );

    if (s) {
      const diferencia = Math.abs(p.indice_riesgo - s.indice_riesgo);
      comparativa.textContent =
        `${motor.toUpperCase()} ${num(p.indice_riesgo)} · ${otroMotor.toUpperCase()} ${num(s.indice_riesgo)} ` +
        `(±${num(motor === "profundo" ? p.incertidumbre_mm_s : s.incertidumbre_mm_s, 2)} mm/s) — ` +
        (diferencia < 8 ? "los motores coinciden" : "los motores DIVERGEN: desconfiar");
      comparativa.dataset.acuerdo = String(diferencia < 8);
    } else {
      comparativa.textContent = `Motor ${motor.toUpperCase()} (el otro motor aún no está listo)`;
      comparativa.dataset.acuerdo = "true";
    }

    const lista_avisos = [...(p.advertencias ?? [])];
    if (p.fuera_de_dominio) lista_avisos.unshift("Fuera del dominio de entrenamiento: extrapolación.");
    avisos.replaceChildren(
      ...lista_avisos.map((/** @type {string} */ texto) => {
        const li = document.createElement("li");
        li.textContent = texto;
        return li;
      }),
    );
    avisos.hidden = lista_avisos.length === 0;
  }

  return {
    /** Factores de la última explicación (para el mensaje de factor dominante). */
    factores() {
      return ultimosFactores;
    },
    /**
     * Pinta los mensajes estructurados; el crítico es role="alert".
     * @param {{ tipo: string, severidad: string, texto: string, nota?: string }[]} lista
     */
    fijarMensajes(lista) {
      mensajes.replaceChildren(
        ...lista.map((m) => {
          const li = document.createElement("li");
          li.className = "mensaje";
          li.dataset.tipo = m.tipo;
          li.dataset.severidad = m.severidad;
          if (m.severidad === "critica") li.setAttribute("role", "alert");
          const p = document.createElement("p");
          p.textContent = m.texto;
          li.append(p);
          if (m.nota) {
            const n = document.createElement("small");
            n.textContent = m.nota;
            li.append(n);
          }
          return li;
        }),
      );
      mensajes.hidden = lista.length === 0;
    },
    /** Recibe las condiciones actuales; limita a una consulta cada INTERVALO_MS. @param {object} condiciones */
    notificar(condiciones) {
      pendiente = condiciones;
      const espera = INTERVALO_MS - (Date.now() - ultimoEnvio);
      if (espera <= 0) {
        ejecutar(condiciones);
      } else if (temporizador === undefined) {
        temporizador = setTimeout(() => {
          temporizador = undefined;
          if (pendiente) ejecutar(pendiente);
        }, espera);
      }
    },
  };
}
