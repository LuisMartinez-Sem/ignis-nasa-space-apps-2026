// @ts-check
/**
 * Demo guiada de la consola de Investigaciones (≈ 90 s). Recorre el producto con acciones REALES (no capturas):
 * carga un CSV de prueba, lo muestra en ranking, Pareto y mapa, compara, evalúa la base lunar y abre el Monitor.
 * Al terminar (o al salir) deshace lo que ella misma cargó: el catálogo real nunca queda alterado por la demo.
 * Teclado: → siguiente, ← anterior, espacio pausa, Esc sale. Con «reducir movimiento» arranca en modo manual.
 */
import { h } from "./dom.js";

/**
 * @typedef {Object} Acciones
 * @property {(tab: string) => void} irA
 * @property {(id: string) => void} seleccionar
 * @property {(ids: string[]) => void} fijarComparadas
 * @property {() => Promise<string[]>} cargarEjemplo   Importa el CSV de ejemplo y devuelve los ids nuevos.
 * @property {() => Promise<void>} quitarPrueba
 * @property {() => boolean} hayPrueba
 * @property {(o2: number, p: number) => void} sondearMapa
 * @property {() => void} abrirMonitor
 * @property {(entorno: string) => void} fijarEntorno
 */

/** Contexto mutable que comparten los pasos. @typedef {{ nuevos: string[], cargoPrueba: boolean }} Contexto */

/**
 * Pasos del recorrido. Es una función pura sobre datos: se puede probar sin navegador.
 * @returns {{ titulo: string, texto: string, segundos: number, foco?: string, entrar: (a: Acciones, c: Contexto) => Promise<void> | void }[]}
 */
export function pasosDemo() {
  return [
    { titulo: "El problema", segundos: 9,
      texto: "La NASA acumula décadas de experimentos de fuego en microgravedad y es difícil encontrarlos, compararlos e interpretarlos. IGNIS los ordena según el entorno que importa: aquí, la base lunar.",
      entrar: (a) => { a.fijarEntorno("luna"); a.irA("analisis"); }, foco: "#inv-kpis" },
    { titulo: "Ranking y por qué", segundos: 10,
      texto: "Cada investigación recibe un puntaje de relevancia con su desglose: qué suma (O₂, presión, combustible…) y qué falta. Todo es una heurística de diseño, no validada por expertos, y lo desconocido se marca como desconocido.",
      entrar: (a) => { a.irA("analisis"); }, foco: "#inv-lista" },
    { titulo: "Entran datos nuevos", segundos: 10,
      texto: "Simulamos la llegada de datos: un CSV con tres investigaciones de ejemplo. IGNIS entiende las columnas, convierte unidades y lo marca como PRUEBA. No toca el catálogo real y se revierte al terminar.",
      entrar: async (a, c) => { if (!a.hayPrueba()) { c.nuevos = await a.cargarEjemplo(); c.cargoPrueba = true; } a.irA("analisis"); if (c.nuevos[0]) a.seleccionar(c.nuevos[0]); }, foco: "#inv-lista" },
    { titulo: "Pareto: qué priorizar", segundos: 11,
      texto: "Eje X: evidencia disponible. Eje Y: riesgo del modelo. Arriba a la izquierda están las condiciones más críticas con menos respaldo experimental: ahí conviene investigar primero. La banda muestra la incertidumbre (P10–P90).",
      entrar: (a) => { a.irA("pareto"); }, foco: "#inv-p-pareto .lienzo-caja" },
    { titulo: "Mapa de riesgo vivo", segundos: 11,
      texto: "El campo de color es el índice del modelo según O₂ y presión. Las cajas son lo que cada investigación declara haber probado. Probamos un punto lunar: 30 % de O₂ y 70 kPa.",
      entrar: (a) => { a.irA("mapa"); setTimeout(() => a.sondearMapa(30, 70), 700); }, foco: "#inv-p-mapa .lienzo-caja" },
    { titulo: "Comparar sin casillas", segundos: 10,
      texto: "Con el botón ＋ se eligen de 2 a 4 investigaciones. La rejilla muestra quién gana en cada componente y la tabla, solo en lo que difieren.",
      entrar: (a, c) => { a.fijarComparadas(["saffire-i", ...(c.nuevos[0] ? [c.nuevos[0]] : ["saffire-ii"])]); a.irA("comparar"); }, foco: "#inv-comparar" },
    { titulo: "Base lunar frente a la ISS", segundos: 10,
      texto: "Una atmósfera con ≥ 30 % de O₂ y ≤ 70,3 kPa puntúa más riesgo que la ISS. Los controles se mantienen dentro del dominio donde el modelo fue entrenado; fuera de él, IGNIS no evalúa.",
      entrar: (a) => { a.irA("luna"); }, foco: "#inv-luna" },
    { titulo: "Hoja de ruta y mejoras", segundos: 9,
      texto: "Lo que la NASA aún no publica (p. ej. gravedad parcial) son oportunidades de investigación, y lo que IGNIS todavía no hace tiene versión y siguiente paso. Decirlo con claridad es parte del producto.",
      entrar: (a) => { a.irA("huecos"); }, foco: "#inv-huecos" },
    { titulo: "Del espacio a la Tierra", segundos: 8,
      texto: "Lo aprendido sin gravedad vuelve como tecnología terrestre: extintores de agua nebulizada, detección de humo y equipo de bomberos. Cada tarjeta enlaza con las investigaciones que la sustentan.",
      entrar: (a) => { a.irA("tierra"); }, foco: "#inv-tierra" },
    { titulo: "Del análisis al gemelo", segundos: 9,
      texto: "Cualquier atmósfera evaluada se puede abrir en el Monitor: el gemelo digital, el detector y el copiloto trabajan con esas mismas condiciones. Fin del recorrido; los datos de prueba se retiran al salir.",
      entrar: (a) => { a.abrirMonitor(); } },
  ];
}

/** Índice acotado al recorrido (sin dar la vuelta). @param {number} i @param {number} n */
export const acotar = (i, n) => Math.min(n - 1, Math.max(0, i));

/**
 * @param {{ boton: HTMLElement, acciones: Acciones, reducirMovimiento?: () => boolean }} o
 */
export function crearDemo(o) {
  const pasos = pasosDemo();
  /** @type {Contexto} */ let ctx = { nuevos: [], cargoPrueba: false };
  let i = -1, pausado = false, temporizador = 0, token = 0;

  const barra = h("span", "demo-progreso"), relleno = h("span");
  barra.append(relleno);
  const contador = h("span", "demo-n mono"), titulo = h("strong", "demo-titulo"), texto = h("p", "demo-texto");
  /** @param {string} t @param {string} etq @param {() => void} f */
  const boton = (t, etq, f) => { const b = /** @type {HTMLButtonElement} */ (h("button", "boton", t)); b.type = "button"; b.setAttribute("aria-label", etq); b.addEventListener("click", f); return b; };
  const bAnt = boton("◀", "Paso anterior", () => ir(i - 1)), bPausa = boton("❚❚", "Pausar", () => alternarPausa()), bSig = boton("▶", "Paso siguiente", () => ir(i + 1)), bSalir = boton("Salir", "Salir de la demo", () => salir());
  const caja = h("section", "demo-caja");
  /** @type {Element|null} */ let enfocado = null;
  function quitarFoco() { enfocado?.classList.remove("demo-foco"); enfocado = null; }
  /** Resalta y lleva a la vista el elemento de lo que se está explicando (el aviso va abajo y no lo tapa). @param {string|undefined} sel */
  function ponerFoco(sel) {
    quitarFoco();
    const el = sel ? document.querySelector(sel) : null;
    if (!el || /** @type {HTMLElement} */ (el).offsetParent === null) return;
    enfocado = el; el.classList.add("demo-foco");
    el.scrollIntoView({ block: "start", behavior: (o.reducirMovimiento?.() ?? false) ? "auto" : "smooth" });
  }
  caja.setAttribute("role", "region"); caja.setAttribute("aria-label", "Demo guiada"); caja.setAttribute("aria-live", "polite"); caja.hidden = true;
  const fila = h("div", "demo-fila"); fila.append(bAnt, bPausa, bSig, bSalir);
  const pie = h("div", "demo-pie"); pie.append(h("span", "demo-teclas", "Teclas: ← → cambian de paso · Espacio pausa · Esc sale"), fila);
  const cab = h("div", "demo-cab"); cab.append(contador, titulo);
  caja.append(barra, cab, texto, pie);
  document.body.append(caja);

  function programar() {
    clearTimeout(temporizador);
    relleno.style.transition = "none"; relleno.style.width = "0%";
    if (pausado || i < 0 || i >= pasos.length) return;
    const s = Math.min(11, Math.max(9, pasos[i].segundos)); // cada paso dura entre 9 y 11 s
    requestAnimationFrame(() => { relleno.style.transition = `width ${s}s linear`; relleno.style.width = "100%"; });
    temporizador = /** @type {any} */ (setTimeout(() => { if (i < pasos.length - 1) ir(i + 1); else salir(); }, s * 1000));
  }

  function alternarPausa() {
    pausado = !pausado;
    bPausa.textContent = pausado ? "▶▶" : "❚❚"; bPausa.setAttribute("aria-label", pausado ? "Reanudar" : "Pausar");
    programar();
  }

  /** @param {number} destino */
  async function ir(destino) {
    if (destino >= pasos.length) { salir(); return; }
    const mio = ++token;
    i = acotar(destino, pasos.length);
    const p = pasos[i];
    contador.textContent = `${i + 1}/${pasos.length}`; titulo.textContent = p.titulo; texto.textContent = p.texto;
    bAnt.disabled = i === 0;
    clearTimeout(temporizador); relleno.style.transition = "none"; relleno.style.width = "0%";
    try { await Promise.race([Promise.resolve(p.entrar(o.acciones, ctx)), new Promise((r) => setTimeout(r, 2500))]); /* un paso lento no detiene el recorrido */ } catch (error) { console.error("[IGNIS] paso de la demo", error); }
    if (mio === token) setTimeout(() => { if (mio === token) ponerFoco(p.foco); }, 450);
    if (mio === token) programar();
  }

  async function salir() {
    token++; clearTimeout(temporizador); i = -1;
    caja.hidden = true; quitarFoco(); window.removeEventListener("keydown", teclas, true);
    o.boton.setAttribute("aria-pressed", "false");
    if (ctx.cargoPrueba) { try { await o.acciones.quitarPrueba(); } catch (error) { console.error("[IGNIS] retirar datos de la demo", error); } }
    o.acciones.fijarComparadas([]);
    ctx = { nuevos: [], cargoPrueba: false };
    o.boton.focus();
  }

  /** @param {KeyboardEvent} e */
  function teclas(e) {
    const t = /** @type {HTMLElement|null} */ (e.target);
    if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    // Captura en la ventana: funciona sea cual sea el elemento enfocado y evita que las pestañas respondan a la vez a las flechas.
    const accion = e.key === "Escape" ? salir : e.key === "ArrowRight" ? () => ir(i + 1) : e.key === "ArrowLeft" ? () => ir(i - 1)
      : e.key === " " ? alternarPausa : null;
    if (!accion) return;
    e.preventDefault(); e.stopPropagation(); accion();
  }

  o.boton.setAttribute("aria-pressed", "false");
  o.boton.addEventListener("click", () => {
    if (i >= 0) { salir(); return; }
    caja.hidden = false; o.boton.setAttribute("aria-pressed", "true");
    pausado = false; // avanza sola siempre; con movimiento reducido solo se quita la animación de la barra
    bPausa.textContent = pausado ? "▶▶" : "❚❚";
    window.addEventListener("keydown", teclas, true);
    ir(0);
    bSig.focus();
  });
  return { salir, get activa() { return i >= 0; } };
}
