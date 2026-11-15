// @ts-check
/**
 * HUD: traduce mensajes del servidor a DOM accesible.
 * Todo texto del servidor entra por textContent (nunca innerHTML): sin XSS.
 */
import { obtener } from "./dom.js";
import {
  COLOR_NIVEL,
  TEXTO_NIVEL,
  VELOCIDAD_NORMALIZACION_MM_S,
  normalizarNivel,
} from "./paleta.js";

const MAX_HISTORIAL = 120;
const TEXTO_CONEXION = { conectado: "Conectado", conectando: "Conectando…", desconectado: "Desconectado" };
const TEXTO_LLAMA_FRIA = {
  NO_EVALUADA: "Sin lectura de temperatura de reacción",
  INACTIVA: "Sin indicios de llama fría",
  POSIBLE: "Llama fría posible: confirmar con termografía",
  PROBABLE: "Llama fría probable: invisible a cámaras visibles",
};

/**
 * @param {unknown} valor @param {number} [decimales]
 * @returns {string}
 */
const formatear = (valor, decimales = 1) =>
  typeof valor === "number" && Number.isFinite(valor) ? valor.toFixed(decimales) : "—";

/**
 * Crea el controlador del HUD (una sola vez, tras cargar el DOM).
 */
export function crearHud() {
  const refs = {
    conexion: obtener("chip-conexion"),
    origen: obtener("chip-origen"),
    anuncio: obtener("anuncio"),
    gauge: obtener("nucleo-gauge"),
    numero: obtener("lectura-numero"),
    nivel: obtener("lectura-nivel"),
    o2: obtener("dato-o2"),
    flujo: obtener("dato-flujo"),
    presion: obtener("dato-presion"),
    tAmb: obtener("dato-tamb"),
    tReaccion: obtener("dato-treaccion"),
    material: obtener("dato-material"),
    espesor: obtener("dato-espesor"),
    medPropagacion: obtener("medidor-propagacion"),
    valPropagacion: obtener("valor-propagacion"),
    medVelocidad: obtener("medidor-velocidad"),
    valVelocidad: obtener("valor-velocidad"),
    medFria: obtener("medidor-fria"),
    valFria: obtener("valor-fria"),
    fria: obtener("fria-estado"),
    friaTexto: obtener("fria-texto"),
    acciones: obtener("lista-acciones"),
    accionesVacio: obtener("acciones-vacio"),
    aviso: obtener("aviso-datos"),
    errorManual: obtener("error-manual"),
  };
  const lienzoHistorial = /** @type {HTMLCanvasElement} */ (obtener("lienzo-historial"));

  /** @type {number[]} */ const historial = [];
  /** @type {string|null} */ let nivelPrevio = null;
  /** @type {import("./paleta.js").NivelRiesgo} */ let nivelActual = "NOMINAL";
  let claveAcciones = "";
  let numeroMostrado = "";

  /**
   * @param {HTMLElement} medidor @param {HTMLElement} etiqueta
   * @param {number} porcentaje @param {string} texto
   */
  function fijarMedidor(medidor, etiqueta, porcentaje, texto) {
    const acotado = Math.min(100, Math.max(0, porcentaje));
    medidor.setAttribute("aria-valuenow", String(Math.round(acotado)));
    medidor.setAttribute("aria-valuetext", texto);
    const relleno = medidor.firstElementChild;
    if (relleno instanceof HTMLElement) relleno.style.width = `${acotado}%`;
    etiqueta.textContent = texto;
  }

  /** @param {unknown} detalle Cadena o lista de errores de validación de Pydantic. */
  function mostrarError(detalle) {
    if (!detalle) {
      refs.errorManual.textContent = "";
      return;
    }
    if (Array.isArray(detalle)) {
      refs.errorManual.textContent = detalle
        .map((d) => `${Array.isArray(d?.loc) ? d.loc.join(".") : "?"}: ${String(d?.msg ?? "inválido")}`)
        .join(" · ");
    } else {
      refs.errorManual.textContent = String(detalle);
    }
  }

  /** @param {unknown} acciones */
  function pintarAcciones(acciones) {
    const lista = Array.isArray(acciones) ? acciones.filter((a) => typeof a === "string") : [];
    const clave = lista.join("\n");
    if (clave !== claveAcciones) {
      // Solo se repinta si cambió: así la animación de entrada marca lo nuevo
      claveAcciones = clave;
      refs.acciones.replaceChildren(
        ...lista.map((texto) => {
          const item = document.createElement("li");
          item.textContent = texto;
          return item;
        }),
      );
    }
    refs.accionesVacio.hidden = lista.length > 0;
  }

  function dibujarHistorial() {
    const caja = lienzoHistorial.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const anchoPx = Math.max(1, Math.round(caja.width * dpr));
    const altoPx = Math.max(1, Math.round(caja.height * dpr));
    if (lienzoHistorial.width !== anchoPx || lienzoHistorial.height !== altoPx) {
      lienzoHistorial.width = anchoPx;
      lienzoHistorial.height = altoPx;
    }
    const ctx = lienzoHistorial.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const { width: ancho, height: alto } = caja;
    ctx.clearRect(0, 0, ancho, alto);

    const y = (/** @type {number} */ valor) => alto - 4 - (valor / 100) * (alto - 8);
    ctx.setLineDash([2, 5]);
    ctx.strokeStyle = "rgba(152,169,194,0.25)";
    ctx.lineWidth = 1;
    for (const frontera of [25, 50, 75]) {
      ctx.beginPath();
      ctx.moveTo(0, y(frontera));
      ctx.lineTo(ancho, y(frontera));
      ctx.stroke();
    }
    ctx.setLineDash([]);
    if (historial.length < 2) return;

    const [r, g, b] = COLOR_NIVEL[nivelActual];
    const paso = ancho / (MAX_HISTORIAL - 1);
    const x = (/** @type {number} */ i) => ancho - (historial.length - 1 - i) * paso;

    ctx.beginPath();
    historial.forEach((valor, i) => (i === 0 ? ctx.moveTo(x(i), y(valor)) : ctx.lineTo(x(i), y(valor))));
    ctx.strokeStyle = `rgb(${r},${g},${b})`;
    ctx.lineWidth = 1.8;
    ctx.stroke();
    ctx.lineTo(x(historial.length - 1), alto);
    ctx.lineTo(x(0), alto);
    ctx.closePath();
    const relleno = ctx.createLinearGradient(0, 0, 0, alto);
    relleno.addColorStop(0, `rgba(${r},${g},${b},0.28)`);
    relleno.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.fillStyle = relleno;
    ctx.fill();
  }

  new ResizeObserver(dibujarHistorial).observe(lienzoHistorial);

  return {
    /**
     * Aplica un mensaje del servidor ({tipo, condiciones, evaluacion} o {tipo:"error"}).
     * @param {any} mensaje
     */
    actualizar(mensaje) {
      if (mensaje?.tipo === "error") {
        mostrarError(mensaje.detalle);
        return;
      }
      const c = mensaje?.condiciones;
      const e = mensaje?.evaluacion;
      if (!c || !e) return;
      mostrarError(null);

      const nivel = normalizarNivel(e.nivel_riesgo);
      nivelActual = nivel;
      document.body.dataset.nivel = nivel;
      const indice = Math.round(Number(e.indice_riesgo) || 0);
      refs.nivel.textContent = TEXTO_NIVEL[nivel];
      refs.gauge.setAttribute("aria-valuenow", String(indice));
      refs.gauge.setAttribute("aria-valuetext", `${indice} de 100, nivel ${TEXTO_NIVEL[nivel]}`);
      if (nivelPrevio !== null && nivel !== nivelPrevio) {
        refs.anuncio.textContent = `Nivel de riesgo ${TEXTO_NIVEL[nivel]}`;
      }
      nivelPrevio = nivel;

      refs.o2.textContent = formatear(c.fraccion_o2 * 100, 1);
      refs.flujo.textContent = formatear(c.velocidad_flujo_cm_s, 1);
      refs.presion.textContent = formatear(c.presion_kpa, 1);
      refs.tAmb.textContent = formatear(c.temperatura_ambiente_k, 0);
      refs.tReaccion.textContent = c.temperatura_reaccion_k == null ? "—" : formatear(c.temperatura_reaccion_k, 0);
      refs.material.textContent = String(c.material ?? "—").toUpperCase();
      refs.espesor.textContent = formatear(c.espesor_combustible_mm, 2);

      const probabilidad = e.probabilidad_propagacion * 100;
      fijarMedidor(refs.medPropagacion, refs.valPropagacion, probabilidad, `${formatear(probabilidad, 0)} %`);
      const velocidad = e.velocidad_propagacion_mm_s;
      fijarMedidor(
        refs.medVelocidad,
        refs.valVelocidad,
        (velocidad / VELOCIDAD_NORMALIZACION_MM_S) * 100,
        `${formatear(velocidad, 2)} ± ${formatear(e.incertidumbre_mm_s, 2)} mm/s`,
      );
      if (e.probabilidad_llama_fria == null) {
        fijarMedidor(refs.medFria, refs.valFria, 0, "—");
        refs.medFria.setAttribute("aria-valuetext", "No evaluada");
      } else {
        const fria = e.probabilidad_llama_fria * 100;
        fijarMedidor(refs.medFria, refs.valFria, fria, `${formatear(fria, 0)} %`);
      }

      const estadoFria = Object.hasOwn(TEXTO_LLAMA_FRIA, e.estado_llama_fria) ? e.estado_llama_fria : "NO_EVALUADA";
      refs.fria.dataset.estado = estadoFria;
      refs.friaTexto.textContent = TEXTO_LLAMA_FRIA[estadoFria];

      pintarAcciones(e.acciones_sugeridas);

      const sintetico = e.origen_datos === "sintetico";
      refs.origen.dataset.origen = sintetico ? "sintetico" : "real";
      refs.origen.textContent = sintetico ? "Datos: sintéticos" : "Datos: reales";
      refs.aviso.hidden = !sintetico;

      historial.push(Number(e.indice_riesgo) || 0);
      if (historial.length > MAX_HISTORIAL) historial.shift();
      dibujarHistorial();
    },

    /** @param {"conectado"|"conectando"|"desconectado"} estado */
    setConexion(estado) {
      refs.conexion.dataset.estado = estado;
      refs.conexion.textContent = TEXTO_CONEXION[estado] ?? estado;
    },

    /**
     * Número grande del núcleo (llamado cada fotograma con el valor interpolado).
     * @param {number} indice
     */
    mostrarIndiceSuavizado(indice) {
      const texto = String(Math.round(indice)).padStart(2, "0");
      if (texto === numeroMostrado) return;
      numeroMostrado = texto;
      refs.numero.textContent = texto;
    },
  };
}
