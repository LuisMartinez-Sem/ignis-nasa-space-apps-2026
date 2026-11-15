// @ts-check
/**
 * Vista principal (reto NASA 2026): consola de misión que resume, ordena e interpreta investigaciones de combustión en microgravedad.
 * Un rail con el ranking a la izquierda y una «estación de análisis» con pestañas a la derecha (detalle, Pareto, mapa, base lunar,
 * comparación, huecos y aplicaciones en la Tierra). Se actualiza sola al detectar datos nuevos. Todo texto del servidor entra con textContent.
 */
import { h, obtener } from "./dom.js";
import { crearAtmosfera } from "./atmosfera.js";
import { crearMapa } from "./mapa.js";
import { crearDemo } from "./demo.js";
import { crearPrueba } from "./prueba.js";
import { crearPareto } from "./pareto.js";
import { crearNotas } from "./notas.js";
import { crearConfianza } from "./confianza.js";
import { etiqueta, etiquetaValor, etiquetarTexto } from "./etiquetas.js";

const API = "/api/v1/investigaciones";
const NOMBRE_COMPONENTE = { o2: "O₂", presion: "Presión", combustible: "Combustible", seguridad: "Áreas de seguridad", datos: "Datos en PSI", gravedad: "Gravedad" };
const NOMBRE_AREA = { prevencion: "Prevención", deteccion: "Detección", supresion: "Supresión" };
const NOMBRE_ENTORNO = { iss: "la ISS", luna: "la base lunar", marte: "Marte", traje: "el traje espacial" };
const MAX_COMPARAR = 4;
const PESTANAS = ["analisis", "pareto", "mapa", "luna", "comparar", "confianza", "huecos", "tierra"];
const PERIODO_SONDEO_MS = 5000;

/** Clase de color según el puntaje. @param {number} p */
export const claseNivel = (p) => (p >= 65 ? "alta" : p >= 45 ? "media" : "baja");

/** Icono por tipo de combustible (solo presentación). */
const ICONO_COMBUSTIBLE = { solido: "▦", gas: "☁", gota: "💧", aerosol: "∴" };
/** @param {string[]} tipos */
const iconosCombustible = (tipos) => tipos.map((t) => ICONO_COMBUSTIBLE[/** @type {keyof typeof ICONO_COMBUSTIBLE} */ (t)] ?? "•").join(" ");
/** Rango numérico legible o «n/d». @param {{min:number|null,max:number|null}|null|undefined} r @param {string} u */
const rangoNum = (r, u) => (!r || (r.min == null && r.max == null) ? "n/d" : r.min === r.max ? `${r.min}${u}` : `${texto(r.min)}–${texto(r.max)}${u}`);

/** Convierte un campo desconocido en texto legible. @param {unknown} v */
export const texto = (v) => (v === null || v === undefined || v === "" ? "n/d" : String(v));

/**
 * Para cada componente del desglose, el id de la investigación con mayor valor (empates: todos).
 * @param {{ investigacion: { id: string }, desglose: { componente: string, valor: number }[] }[]} rankeadas
 * @returns {Record<string, string[]>}
 */
export function mejorPorComponente(rankeadas) {
  /** @type {Record<string, string[]>} */ const mejor = {};
  const comps = new Set(rankeadas.flatMap((r) => r.desglose.map((d) => d.componente)));
  for (const c of comps) {
    const vals = rankeadas.map((r) => [r.investigacion.id, r.desglose.find((d) => d.componente === c)?.valor ?? -1]);
    const max = Math.max(...vals.map((v) => /** @type {number} */ (v[1])));
    mejor[c] = vals.filter((v) => v[1] === max && max >= 0).map((v) => String(v[0]));
  }
  return mejor;
}

/** @param {string} url @param {RequestInit} [opciones] */
async function pedir(url, opciones) {
  const r = await fetch(url, opciones);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/** Anillo de puntaje (conic-gradient animado por CSS). @param {number} v @param {string} clase */
function anillo(v, clase = "") {
  const el = h("div", `anillo ${clase}`.trim());
  el.style.setProperty("--v", String(Math.round(v)));
  el.style.setProperty("--c", v >= 65 ? "var(--cian)" : v >= 45 ? "var(--ambar)" : "var(--texto-3)");
  el.setAttribute("role", "img"); el.setAttribute("aria-label", `Relevancia ${v.toFixed(0)} de 100`);
  el.append(h("strong", "anillo-v mono", v.toFixed(0)));
  return el;
}

/**
 * @param {{ alCargarEnMonitor?: (monitor: { modo: string, sliders: Record<string, number|boolean> }) => void }} [opciones]
 */
/** Solo presentación: marca el entorno en <body> (color propio) y dispara un fundido breve; la lógica no depende de esto. @param {string} e @param {boolean} [animar] */
function marcarEntorno(e, animar = false) {
  document.body.dataset.entorno = e;
  if (!animar) return;
  document.body.classList.remove("cambia-entorno");
  void document.body.offsetWidth; // reinicia la animación CSS
  document.body.classList.add("cambia-entorno");
  setTimeout(() => document.body.classList.remove("cambia-entorno"), 450);
}

export function crearInvestigaciones(opciones = {}) {
  const lista = obtener("inv-lista"), estado = obtener("inv-estado"), kpis = obtener("inv-kpis"), bandeja = obtener("inv-bandeja");
  const selArea = /** @type {HTMLSelectElement} */ (obtener("inv-filtro-area")), selComb = /** @type {HTMLSelectElement} */ (obtener("inv-filtro-comb"));
  const aviso = obtener("inv-toast");
  let entorno = "luna", seleccion = "", pestana = "analisis", huella = "";
  marcarEntorno(entorno);
  /** @type {any[]} */ let resultados = [];
  /** @type {any[]} */ let catalogo = [];
  /** @type {any} */ let estadoCat = null;
  /** @type {string[]} */ let comparadas = [];
  let cargado = false, solicitud = 0, frontera = null;
  /** @type {any[]|null} */ let huecosCache = null;
  /** @type {any[]|null} */ let tierraCache = null;
  const iniciadas = new Set();

  const pareto = crearPareto({
    lienzo: /** @type {HTMLCanvasElement} */ (obtener("inv-pareto-lienzo")), barra: obtener("inv-pareto-barra"), resumen: obtener("inv-pareto-resumen"),
    lista: obtener("inv-pareto-lista"), detalle: obtener("inv-pareto-detalle"), aviso: obtener("inv-pareto-aviso"), obtenerEntorno: () => entorno,
    alSeleccionar: (id, destino) => { seleccionar(id, false); if (destino) irA(destino); },
  });
  const mapa = crearMapa({
    lienzo: /** @type {HTMLCanvasElement} */ (obtener("inv-mapa-lienzo")), lectura: obtener("inv-mapa-lectura"), sonda: obtener("inv-mapa-sonda"),
    leyenda: obtener("inv-mapa-leyenda"), capas: obtener("inv-mapa-capas"), alCargarEnMonitor: opciones.alCargarEnMonitor,
    alSeleccionar: (id) => { seleccionar(id); irA("analisis"); },
  });
  const confianza = crearConfianza({ entorno: () => entorno, nombres: () => resultados.map((x) => ({ id: x.investigacion.id, nombre: x.investigacion.nombre })) });
  const nombreDe = (/** @type {string} */ id) => resultados.find((x) => x.investigacion.id === id)?.investigacion.nombre ?? catalogo.find((x) => x.investigacion.id === id)?.investigacion.nombre ?? id;
  const notas = crearNotas({ boton: obtener("boton-notas"), seleccion: () => seleccion, nombre: nombreDe, ir: (id) => { buscar.value = ""; seleccionar(id); irA("analisis"); } });
  const luna = crearAtmosfera({ contenedor: obtener("inv-luna"), alCargarEnMonitor: opciones.alCargarEnMonitor, alVerEnMapa: (o2, p) => { irA("mapa"); setTimeout(() => mapa.sondear(o2, p), 350); } });

  // ------------------------------------------------------------------------------------------ datos
  async function cargarRanking() {
    const mia = ++solicitud;
    lista.setAttribute("aria-busy", "true");
    const q = new URLSearchParams({ entorno });
    if (selArea.value) q.set("area", selArea.value);
    if (selComb.value) q.set("combustible", selComb.value);
    try {
      const datos = await pedir(`${API}/ranking?${q}`);
      if (mia !== solicitud) return;
      resultados = datos.resultados; estadoCat = datos.estado; huella = datos.estado?.huella ?? huella;
      const respaldo = datos.estado?.origen === "respaldo";
      estado.textContent = `${respaldo ? "⚠ CATÁLOGO DE RESPALDO (el archivo no se pudo leer). " : ""}${datos.total} investigaciones para ${datos.entorno.nombre}. ${datos.entorno.nota}` +
        (datos.estado?.ingesta_aplicada?.length ? ` Datos NASA ingeridos para: ${datos.estado.ingesta_aplicada.join(", ")}.` : "");
      estado.dataset.origen = datos.estado?.origen ?? "archivo";
      if (!resultados.some((r) => r.investigacion.id === seleccion)) seleccion = resultados[0]?.investigacion.id ?? "";
      notas.cambioSeleccion(); pintarLista(); pintarDetalle(); pintarKpis(); pintarBandeja(); prueba.mostrarEstado(estadoCat?.prueba ?? []);
      if (pestana === "comparar") pintarComparar();
    } catch (error) {
      if (mia !== solicitud) return;
      console.error("[IGNIS] ranking", error);
      estado.textContent = "No se pudo cargar el ranking. ¿El servidor está activo?";
      lista.replaceChildren();
    } finally {
      if (mia === solicitud) lista.setAttribute("aria-busy", "false");
    }
  }

  async function cargarCatalogo() {
    try { catalogo = (await pedir(API)).items; pintarKpis(); } catch (error) { console.error("[IGNIS] catálogo", error); }
  }

  // ------------------------------------------------------------------------------------------ resumen
  function pintarKpis() {
    const mejor = resultados[0];
    const conO2 = catalogo.filter((c) => c.investigacion.o2_pct.min !== null && c.investigacion.o2_pct.max !== null).length;
    const nuevas = estadoCat?.nuevas_ingestadas?.length ?? 0, ing = estadoCat?.ingesta_aplicada?.length ?? 0;
    const tarjetas = [
      ["Investigaciones", String(catalogo.length || resultados.length), nuevas || ing ? `${ing} con datos NASA · ${nuevas} nueva(s)` : "catálogo del equipo"],
      [`Mejor para ${NOMBRE_ENTORNO[/** @type {keyof typeof NOMBRE_ENTORNO} */ (entorno)] ?? entorno}`, mejor ? mejor.investigacion.nombre : "—", mejor ? `${mejor.puntaje.toFixed(0)} / 100` : ""],
      ["Con O₂ conocido", `${conO2} / ${catalogo.length || "—"}`, "el resto espera los metadatos de PSI"],
      ["Frontera de Pareto", frontera === null ? "—" : String(frontera), "las más críticas (riesgo alto, poca evidencia)"],
    ];
    kpis.replaceChildren(...tarjetas.map(([k, v, s]) => { const t = h("div", "kpi"); t.append(h("span", "kpi-k", k), h("strong", "kpi-v mono", v), h("span", "kpi-s", s)); return t; }));
  }

  // ------------------------------------------------------------------------------------------ rail
  /** Texto en minúsculas y sin acentos para comparar. @param {string} t */
  const norm = (t) => String(t).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  /** ¿La investigación coincide con la búsqueda? Cada palabra debe aparecer en nombre, combustible, hardware o id. @param {any} i @param {string} q */
  const coincide = (i, q) => { const m = norm(`${i.nombre} ${i.id} ${i.combustible_tipos.join(" ")} ${i.combustible_detalle ?? ""} ${i.hardware.join(" ")}`); return norm(q).split(/\s+/).filter(Boolean).every((w) => m.includes(w)); };
  const buscar = /** @type {HTMLInputElement} */ (obtener("inv-buscar")), buscarX = obtener("inv-buscar-limpiar"), buscarN = obtener("inv-buscar-cuenta");
  buscar.addEventListener("input", () => { pintarLista(); });
  buscarX.addEventListener("click", () => { buscar.value = ""; pintarLista(); buscar.focus(); });
  buscar.addEventListener("keydown", (e) => { if (e.key === "Escape" && buscar.value) { e.stopPropagation(); buscar.value = ""; pintarLista(); } });

  function pintarLista() {
    const q = buscar.value.trim(), visibles = q ? resultados.filter((r) => coincide(r.investigacion, q)) : resultados;
    buscarX.hidden = !q; buscarN.hidden = !q;
    buscarN.textContent = visibles.length ? `${visibles.length} de ${resultados.length} investigaciones` : `Ninguna investigación coincide con «${q}».`;
    lista.replaceChildren(...visibles.map((r) => {
      const i = r.investigacion, li = h("li", "inv-item");
      const b = /** @type {HTMLButtonElement} */ (h("button", "inv-tarjeta"));
      b.type = "button"; b.dataset.nivel = claseNivel(r.puntaje); b.setAttribute("aria-pressed", String(i.id === seleccion));
      const barra = h("span", "inv-barra"), rel = h("span"); rel.style.height = `${r.puntaje}%`; barra.append(rel); barra.setAttribute("aria-hidden", "true");
      const nuevo = estadoCat?.nuevas_ingestadas?.includes(i.id), deprueba = estadoCat?.prueba?.includes(i.id);
      b.append(h("span", "inv-pos mono", `#${r.posicion}`), h("strong", "inv-nombre", i.nombre + (deprueba ? " · PRUEBA" : nuevo ? " · NUEVA" : "")), h("span", "inv-puntaje mono", r.puntaje.toFixed(0)),
        h("span", "inv-tipo", `${iconosCombustible(i.combustible_tipos)} ${i.combustible_tipos.join("/") || "sin clasificar"} · ${i.hardware.join(", ") || "hardware n/d"}`), barra, h("span", "inv-confianza", `confianza ${r.confianza}`));
      b.addEventListener("click", () => seleccionar(i.id));
      const pin = /** @type {HTMLButtonElement} */ (h("button", "inv-pin"));
      const en = comparadas.includes(i.id);
      pin.type = "button"; pin.setAttribute("aria-pressed", String(en)); pin.title = en ? "Quitar de la comparación" : "Añadir a la comparación"; pin.setAttribute("aria-label", `${en ? "Quitar de" : "Añadir a"} la comparación: ${i.nombre}`);
      pin.textContent = en ? "✓" : "＋";
      pin.addEventListener("click", () => alternarComparar(i.id));
      li.append(b, pin);
      return li;
    }));
  }

  function pintarBandeja() {
    bandeja.hidden = comparadas.length === 0;
    if (!comparadas.length) return;
    const nombre = (/** @type {string} */ id) => resultados.find((r) => r.investigacion.id === id)?.investigacion.nombre ?? catalogo.find((c) => c.investigacion.id === id)?.investigacion.nombre ?? id;
    const fichas = comparadas.map((id) => { const c = h("span", "ficha-cmp"); const x = /** @type {HTMLButtonElement} */ (h("button", "ficha-x", "×")); x.type = "button"; x.setAttribute("aria-label", `Quitar ${nombre(id)}`); x.addEventListener("click", () => alternarComparar(id)); c.append(h("span", null, nombre(id)), x); return c; });
    const ir = /** @type {HTMLButtonElement} */ (h("button", "boton", `Comparar (${comparadas.length})`));
    ir.type = "button"; ir.disabled = comparadas.length < 2; ir.addEventListener("click", () => irA("comparar"));
    bandeja.replaceChildren(h("span", "inv-etq", comparadas.length < 2 ? "Elige al menos 2 con ＋" : "En comparación"), ...fichas, ir);
    obtener("tab-comparar-n").textContent = comparadas.length ? ` ${comparadas.length}` : "";
  }

  /** @param {string} id */
  function alternarComparar(id) {
    if (comparadas.includes(id)) comparadas = comparadas.filter((x) => x !== id);
    else if (comparadas.length < MAX_COMPARAR) comparadas = [...comparadas, id];
    else { avisar(`Máximo ${MAX_COMPARAR} investigaciones; quita una para añadir otra.`); return; }
    pintarLista(); pintarBandeja();
    if (pestana === "comparar") pintarComparar();
  }

  // ------------------------------------------------------------------------------------------ navegación
  /** @param {string} id @param {boolean} [notificar] */
  function seleccionar(id, notificar = true) {
    seleccion = id; notas.cambioSeleccion(); pintarLista(); pintarDetalle();
    if (notificar) pareto.resaltar(id);
    else pareto.resaltar(id);
  }

  /** @param {string} destino */
  function irA(destino) {
    if (!PESTANAS.includes(destino)) return;
    pestana = destino;
    for (const t of /** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-inv-tab]"))) {
      const act = t.dataset.invTab === destino;
      t.setAttribute("aria-selected", String(act)); t.tabIndex = act ? 0 : -1;
      obtener(`inv-p-${t.dataset.invTab}`).hidden = !act;
    }
    mapa.activar(destino === "mapa");
    if (destino === "pareto") pareto.redibujar();
    if (destino === "pareto" && !iniciadas.has("pareto")) { iniciadas.add("pareto"); pareto.cargar().then(() => pareto.resaltar(seleccion)); } else if (destino === "pareto") pareto.recargarSiCambio();
    if (destino === "mapa") { iniciadas.add("mapa"); mapa.cargar(); }
    if (destino === "luna") luna.activar();
    if (destino === "comparar") pintarComparar();
    if (destino === "confianza") confianza.pintar(seleccion);
    if (destino === "huecos") pintarHuecos();
    if (destino === "tierra") pintarTierra();
  }

  function avisar(/** @type {string} */ msg) {
    aviso.textContent = msg; aviso.hidden = false;
    clearTimeout(/** @type {any} */ (aviso.dataset.t)); aviso.dataset.t = String(setTimeout(() => { aviso.hidden = true; }, 6000));
  }

  // ------------------------------------------------------------------------------------------ análisis (detalle)
  function pintarDetalle() {
    const cont = obtener("inv-detalle");
    const r = resultados.find((x) => x.investigacion.id === seleccion);
    if (!r) { cont.replaceChildren(h("p", "vacio", "Elige una investigación del ranking.")); return; }
    const i = r.investigacion;
    const cab = h("div", "det-cab");
    const txt = h("div"); txt.append(h("h3", "inv-titulo", i.nombre_completo), h("p", "det-sub", `${i.instalacion} · ${i.familia} · confianza ${r.confianza}`), h("p", "inv-interp", r.interpretacion));
    cab.append(anillo(r.puntaje, "anillo-grande"), txt);
    const desglose = h("ul", "inv-desglose");
    for (const d of r.desglose) {
      const li = h("li"), barra = h("span", "inv-barra"), rel = h("span"); rel.style.width = `${d.valor * 100}%`; barra.append(rel);
      li.append(h("span", null, `${NOMBRE_COMPONENTE[/** @type {keyof typeof NOMBRE_COMPONENTE} */ (d.componente)] ?? d.componente} (peso ${d.peso})`), barra, h("span", "mono", d.aporte.toFixed(1)), h("small", null, d.motivo));
      desglose.append(li);
    }
    const o2 = i.o2_pct.min === null && i.o2_pct.max === null ? "desconocido" : `${texto(i.o2_pct.min)}–${texto(i.o2_pct.max)} %`;
    const hechos = h("dl", "inv-ficha");
    for (const [k, v] of /** @type {[string, string][]} */ ([["Objetivos", i.objetivos], ["Combustible", i.combustible_detalle], ["Hardware", i.hardware.join(", ")], ["Áreas de seguridad", i.areas_seguridad.join(", ") || "sin clasificar"],
      ["Gravedad", etiquetaValor(i.gravedad)], ["O₂ de las pruebas", o2], ["Datos en PSI", i.datos_en_psi === null ? "no verificado" : i.datos_en_psi ? "sí" : "todavía no"], ["Fuente", i.fuente]])) hechos.append(h("dt", null, k), h("dd", null, texto(v)));
    const faltan = h("div", "chips"); faltan.append(h("span", "inv-etq", "Campos no verificados"));
    for (const c of i.campos_no_verificados) faltan.append(h("span", "chip-inf", etiqueta(c)));
    if (!i.campos_no_verificados.length) faltan.append(h("span", "chip-ok", "ninguno"));
    const acc = h("div", "inv-fila");
    for (const [t, f] of /** @type {[string, () => void][]} */ ([[comparadas.includes(i.id) ? "Quitar de la comparación" : "＋ Comparar", () => { alternarComparar(i.id); pintarDetalle(); }], ["Informe de confianza", () => irA("confianza")], ["Ver en el Pareto", () => { pareto.resaltar(i.id); irA("pareto"); }], ["Ver en el mapa", () => irA("mapa")]])) {
      const b = /** @type {HTMLButtonElement} */ (h("button", "boton boton-sec", t)); b.type = "button"; b.addEventListener("click", f);
      acc.append(b);
    }
    const ficha = h("div", "inv-fichagr"); ficha.dataset.confianza = r.confianza;
    const cabF = h("div", "ficha-cab"); cabF.append(h("span", "ficha-conf", `Confianza ${r.confianza}`), i.datos_en_psi ? h("span", "ficha-verif", "✓ Verificado en PSI") : h("span", "ficha-noverif", i.datos_en_psi === null ? "PSI: sin verificar" : "PSI: pendiente"));
    const nums = h("div", "ficha-nums");
    for (const [et, val, sub] of /** @type {[string,string,string][]} */ ([["O₂", rangoNum(i.o2_pct, ""), "%"], ["Presión", rangoNum(i.presion_kpa, ""), "kPa"], ["Combustible", iconosCombustible(i.combustible_tipos), i.combustible_tipos.join(" / ") || "sin clasificar"]])) {
      const c = h("div", "ficha-num"); c.append(h("small", null, et), h("strong", "mono", val), h("span", null, sub)); nums.append(c);
    }
    ficha.append(cabF, nums, hechos);
    cont.replaceChildren(cab, h("h4", "det-sec", "Por qué este puntaje"), desglose, h("h4", "det-sec", "Ficha"), ficha, faltan, acc);
  }

  // ------------------------------------------------------------------------------------------ comparar
  async function pintarComparar() {
    const cont = obtener("inv-comparar");
    if (comparadas.length < 2) {
      cont.replaceChildren(h("p", "vacio", "Usa el botón ＋ de las tarjetas del ranking para elegir de 2 a 4 investigaciones. Aquí verás sus puntajes, qué componente gana cada una y en qué difieren."));
      return;
    }
    const ids = [...comparadas];
    try {
      const [d, rank] = await Promise.all([pedir(`${API}/comparar?ids=${ids.join(",")}`), pedir(`${API}/ranking?entorno=${entorno}&limite=100`)]);
      if (ids.join() !== comparadas.join()) return;
      const por = new Map(rank.resultados.map((/** @type {any} */ r) => [r.investigacion.id, r]));
      const sel = ids.map((id) => por.get(id)).filter(Boolean);
      const mejor = mejorPorComponente(sel);
      const rejilla = h("div", "cmp-rejilla"); rejilla.style.setProperty("--n", String(sel.length));
      rejilla.append(h("span"));
      for (const r of sel) { const c = h("div", "cmp-cab"); const x = /** @type {HTMLButtonElement} */ (h("button", "ficha-x", "×")); x.type = "button"; x.setAttribute("aria-label", `Quitar ${r.investigacion.nombre}`); x.addEventListener("click", () => alternarComparar(r.investigacion.id));
        c.append(anillo(r.puntaje), h("strong", null, r.investigacion.nombre), h("small", null, `#${r.posicion} en ${NOMBRE_ENTORNO[/** @type {keyof typeof NOMBRE_ENTORNO} */ (entorno)] ?? entorno}`), x); rejilla.append(c); }
      for (const comp of Object.keys(NOMBRE_COMPONENTE)) {
        rejilla.append(h("span", "cmp-fila-t", NOMBRE_COMPONENTE[/** @type {keyof typeof NOMBRE_COMPONENTE} */ (comp)]));
        for (const r of sel) {
          const dd = r.desglose.find((/** @type {any} */ q) => q.componente === comp), celda = h("div", "cmp-celda"), barra = h("span", "inv-barra"), rel = h("span"); rel.style.width = `${(dd?.valor ?? 0) * 100}%`; barra.append(rel);
          if (mejor[comp]?.includes(r.investigacion.id) && sel.length > 1 && new Set(sel.map((/** @type {any} */ q) => q.desglose.find((/** @type {any} */ z) => z.componente === comp)?.valor)).size > 1) celda.dataset.mejor = "true";
          celda.append(barra, h("span", "mono", dd ? dd.aporte.toFixed(1) : "—")); celda.title = dd?.motivo ?? ""; rejilla.append(celda);
        }
      }
      const dif = d.filas.filter((/** @type {any} */ f) => !f.iguales);
      const tabla = h("table", "inv-tabla"), cab = h("tr"); cab.append(h("th", null, "Campo"), ...d.ids.map((/** @type {string} */ id) => h("th", null, por.get(id)?.investigacion.nombre ?? id))); tabla.append(cab);
      for (const f of dif) { const tr = h("tr"); tr.append(h("th", null, etiqueta(f.campo)), ...d.ids.map((/** @type {string} */ id) => h("td", null, etiquetaValor(texto(f.valores[id]))))); tabla.append(tr); }
      const iguales = h("p", "inv-nota", `Coinciden en: ${d.similitudes.join(", ") || "nada"}.`);
      cont.replaceChildren(rejilla, h("h4", "det-sec", `En qué se diferencian (${dif.length})`), dif.length ? tabla : h("p", "vacio", "Son idénticas en todos los campos comparados."), iguales);
    } catch (error) {
      console.error("[IGNIS] comparar", error);
      cont.replaceChildren(h("p", "vacio", "No se pudo comparar."));
    }
  }

  // ------------------------------------------------------------------------------------------ hoja de ruta
  /** Siguiente paso de cada límite de IGNIS, con su versión prevista (la severidad del servidor se muestra como «prioridad»). */
  const RUTA = /** @type {Record<string, string>} */ ({
    "sin-modelo-supresion": "v2.0 · módulo de dilución con datos de FLEX (CO₂ y helio)",
    "traje-fuera-de-dominio": "v2.x · ampliar el dominio con CFI-G (hasta 85 % de O₂) tras validarlo",
    "sin-validacion-externa": "Antes de v2.0 · contraste con tablas del NTRS y revisión de un especialista",
  });
  async function pintarHuecos() {
    const cont = obtener("inv-huecos");
    try {
      huecosCache ??= await pedir(`${API}/gaps`);
      const todos = /** @type {any[]} */ (huecosCache);
      const tarjeta = (/** @type {any} */ g, /** @type {string} */ etiqueta, /** @type {string} */ paso) => {
        const t = h("article", "inv-hueco"); t.dataset.severidad = g.severidad;
        t.append(h("span", "sev", `prioridad ${g.severidad}`), h("strong", null, g.titulo), h("p", null, g.detalle), h("small", null, `${etiqueta}: ${paso}`));
        return t;
      };
      const oportunidades = h("section", "hueco-col"); oportunidades.append(h("h4", "det-sec", "Oportunidades abiertas en los datos de la NASA"),
        h("p", "inv-nota", "Lo que PSI todavía no publica. Cada una es un frente de investigación donde IGNIS ya sabe qué hacer mientras tanto."));
      for (const g of todos.filter((x) => x.ambito === "nasa_psi")) oportunidades.append(tarjeta(g, "Qué hace IGNIS mientras tanto", g.accion_sugerida));
      const ruta = h("section", "hueco-col"); ruta.append(h("h4", "det-sec", "Hoja de ruta de IGNIS"),
        h("p", "inv-nota", "Alcance actual y siguiente paso. Lo que no está validado se dice tal cual, porque así se sabe qué falta para confiar en él."));
      for (const g of todos.filter((x) => x.ambito === "ignis")) ruta.append(tarjeta(g, "Siguiente paso", RUTA[g.id] ?? g.accion_sugerida));
      const cubre = h("div", "chips"); cubre.append(h("span", "inv-etq", "Cobertura del reto hoy"));
      for (const [t, c] of [["Prevención · ranking, Pareto, mapa", "chip-ok"], ["Detección · detector temporal y copiloto", "chip-ok"], ["Supresión · guía por reglas; modelo físico en v2.0", "chip-inf"]]) cubre.append(h("span", c, t));
      cont.replaceChildren(cubre, h("div", "hueco-rejilla"));
      cont.querySelector(".hueco-rejilla")?.append(oportunidades, ruta);
    } catch (error) {
      console.error("[IGNIS] hoja de ruta", error);
      cont.replaceChildren(h("p", "vacio", "No se pudo cargar la hoja de ruta."));
    }
  }

  // ------------------------------------------------------------------------------------------ del espacio a la Tierra
  /** Trazado de la llama según la gravedad g (0 = esfera, 1 = lágrima): interpola los cuatro arcos de Bézier. @param {number} g */
  function trazoLlama(g) {
    const k = 24.9, ty = -45 - 50 * g, ry = 5 * g;
    const c1x = k * (1 - g) + 3 * g, c1y = ty + 30 * g;
    return `M0,${ty} C${c1x},${c1y} 45,${ry - k} 45,${ry} C45,${ry + k} ${k},45 0,45 C${-k},45 -45,${ry + k} -45,${ry} C-45,${ry - k} ${-c1x},${c1y} 0,${ty} Z`;
  }
  /** Laboratorio de la llama: un control de gravedad que transforma la llama (esfera azul sin gravedad, lágrima con gravedad). */
  function laboratorioLlama() {
    const caja = h("div", "llama-lab");
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "-90 -110 180 170"); svg.setAttribute("role", "img"); svg.setAttribute("class", "llama-svg");
    const trazo = document.createElementNS(ns, "path"); svg.append(trazo);
    const lectura = h("p", "llama-texto"), valor = h("output", "mono"), inp = /** @type {HTMLInputElement} */ (h("input"));
    inp.type = "range"; inp.min = "0"; inp.max = "1"; inp.step = "0.01"; inp.value = "0"; inp.setAttribute("aria-label", "Gravedad en g");
    const poner = (/** @type {number} */ g) => {
      trazo.setAttribute("d", trazoLlama(g));
      trazo.setAttribute("fill", `rgb(${Math.round(70 + 185 * g)},${Math.round(170 - 50 * g)},${Math.round(255 - 215 * g)})`);
      trazo.setAttribute("opacity", String(0.85 + 0.15 * g));
      valor.textContent = `${g.toFixed(2)} g`;
      lectura.textContent = g < 0.08 ? "Sin gravedad: no hay flotabilidad, el gas caliente no sube y la llama es una esfera azulada que respira por difusión. Es la llama «limpia» que estudian las investigaciones del catálogo."
        : g > 0.92 ? "En la Tierra: la convección eleva los gases calientes y la llama se alarga como una lágrima que parpadea. Esa distorsión es lo que el laboratorio orbital elimina para ver la física pura."
        : "Gravedad intermedia: la forma cambia de forma continua. Importante: PSI aún no tiene datos de combustión en gravedad parcial (LUCI y FM2 los aportarán); aquí solo se ilustra la idea.";
      svg.setAttribute("aria-label", `Llama con ${g.toFixed(2)} g`);
    };
    inp.addEventListener("input", () => poner(+inp.value));
    const atajos = h("div", "chips");
    for (const [n, g] of /** @type {[string, number][]} */ ([["ISS · microgravedad", 0], ["Luna · 0,17 g", 0.166], ["Marte · 0,38 g", 0.38], ["Tierra · 1 g", 1]])) {
      const b = /** @type {HTMLButtonElement} */ (h("button", "chip-inv", n)); b.type = "button"; b.addEventListener("click", () => { inp.value = String(g); poner(g); }); atajos.append(b);
    }
    const ctrl = h("label", "control"); ctrl.append(h("span", null, "Gravedad"), valor, inp);
    caja.append(svg, h("div", null)); caja.lastElementChild?.append(h("h4", "det-sec", "Laboratorio de la llama"), ctrl, atajos, lectura);
    poner(0);
    return caja;
  }

  let areaTierra = "supresion";
  async function pintarTierra() {
    const cont = obtener("inv-tierra");
    try {
      tierraCache ??= await pedir(`${API}/aplicaciones-terrestres`);
      const apps = /** @type {any[]} */ (tierraCache);
      if (!apps.some((a) => a.area === areaTierra)) areaTierra = apps[0]?.area ?? "supresion";
      const a = apps.find((x) => x.area === areaTierra);
      const intro = h("p", "tierra-intro", "IGNIS estudia el fuego sin gravedad porque ahí la llama se ve «limpia»: sin convección que la distorsione. Lo que se aprende no se queda arriba: vuelve como tecnología que ya usamos en la Tierra.");
      const selector = h("div", "segmentos"); selector.setAttribute("role", "group"); selector.setAttribute("aria-label", "Aplicación en la Tierra");
      for (const x of apps) { const b = /** @type {HTMLButtonElement} */ (h("button", "segmento", `${NOMBRE_AREA[/** @type {keyof typeof NOMBRE_AREA} */ (x.area)] ?? x.area}: ${x.tecnologia}`)); b.type = "button"; b.setAttribute("aria-pressed", String(x.area === areaTierra)); b.addEventListener("click", () => { areaTierra = x.area; pintarTierra(); }); selector.append(b); }
      const nodos = [];
      if (a) {
        const rel = catalogo.filter((c) => c.investigacion.areas_seguridad.includes(a.area)).sort((p, q) => (q.relevancia[entorno] ?? 0) - (p.relevancia[entorno] ?? 0));
        const paso = (/** @type {string} */ n, /** @type {string} */ t, /** @type {string} */ d) => { const e = h("div", "tierra-paso"); e.append(h("span", "tierra-n mono", n), h("strong", null, t), h("p", null, d)); return e; };
        const flujo = h("div", "tierra-flujo");
        flujo.append(paso("1", "En órbita", a.por_que), paso("2", "Qué se aprende", `Las investigaciones del catálogo sobre ${NOMBRE_AREA[/** @type {keyof typeof NOMBRE_AREA} */ (a.area)]?.toLowerCase() ?? a.area} (${rel.length}) miden cómo se comporta la llama sin gravedad.`), paso("3", "En la Tierra", `${a.tecnologia}: ${a.uso_en_tierra}`));
        const chips = h("div", "chips"); chips.append(h("span", "inv-etq", "Investigaciones que la sustentan, de más a menos relevantes"));
        for (const c of rel.slice(0, 6)) { const b = /** @type {HTMLButtonElement} */ (h("button", "chip-inv", `${c.investigacion.nombre} · ${(c.relevancia[entorno] ?? 0).toFixed(0)}`)); b.type = "button"; b.addEventListener("click", () => { seleccionar(c.investigacion.id); irA("analisis"); }); chips.append(b); }
        const ver = /** @type {HTMLButtonElement} */ (h("button", "boton", `Filtrar el ranking por ${NOMBRE_AREA[/** @type {keyof typeof NOMBRE_AREA} */ (a.area)] ?? a.area} (${rel.length})`));
        ver.type = "button"; ver.addEventListener("click", () => { selArea.value = a.area; cargarRanking(); irA("analisis"); avisar(`Ranking filtrado por ${NOMBRE_AREA[/** @type {keyof typeof NOMBRE_AREA} */ (a.area)] ?? a.area}.`); });
        nodos.push(h("p", "inv-nota", `Origen: ${a.origen}`), flujo, chips, ver);
      }
      cont.replaceChildren(intro, laboratorioLlama(), h("h4", "det-sec", "De la microgravedad a la Tierra"), selector, ...nodos, h("p", "inv-nota", apps[0]?.aviso ?? ""));
    } catch (error) {
      console.error("[IGNIS] aplicaciones", error);
      cont.replaceChildren(h("p", "vacio", "No se pudieron cargar las aplicaciones."));
    }
  }

  // ------------------------------------------------------------------------------------------ actualización automática
  /** Vuelve a pedir TODO lo que depende del catálogo (ranking, KPIs, Pareto, mapa, huecos, Tierra). */
  /** Avisos de calidad de las tablas PSI cargadas (filas vacías, duplicados, erratas, conflictos): el investigador debe saberlo, no descubrirlo. */
  async function cargarCalidad() {
    const caja = obtener("inv-calidad");
    try {
      const r = await fetch(`${API}/calidad-datos`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const conAviso = d.archivos.filter((/** @type {any} */ a) => a.avisos.length || a.conflictos.length || a.estado === "fallido");
      caja.hidden = d.archivos.length === 0;
      if (caja.hidden) return;
      const { atencion, conflictos, fallidos } = d.resumen;
      const resumen = h("summary", null, `Calidad de los datos NASA cargados: ${d.archivos.length} tabla(s) · ${atencion} aviso(s) a revisar · ${conflictos} conflicto(s)${fallidos ? ` · ${fallidos} fallida(s)` : ""}`);
      const cuerpo = h("div", "calidad-cuerpo");
      cuerpo.append(h("p", "inv-nota", "IGNIS limpia las tablas al leerlas y NO borra ni corrige la fuente: lo descartado queda aquí listado para que lo confirmes con el equipo de la NASA o con el autor de la tabla."));
      for (const a of conAviso) {
        const bloque = h("div", "calidad-archivo");
        bloque.append(h("strong", null, `${a.investigacion ?? a.archivo}`), h("span", "inv-nota", ` · ${a.archivo}${a.filas_utiles ? ` · ${a.filas_utiles} ensayos útiles` : ""}`));
        const ul = h("ul", "calidad-lista");
        if (a.estado === "fallido") ul.append(h("li", "calidad-atencion", `No se pudo leer: ${a.motivo}`));
        for (const c of a.conflictos) ul.append(h("li", "calidad-atencion", `Conflicto con el catálogo: ${etiquetarTexto(c)}`));
        for (const x of a.avisos) ul.append(h("li", x.nivel === "atencion" ? "calidad-atencion" : "calidad-info", x.texto));
        bloque.append(ul); cuerpo.append(bloque);
      }
      caja.replaceChildren(resumen, cuerpo);
      caja.dataset.nivel = atencion || conflictos || fallidos ? "atencion" : "ok";
    } catch (error) { console.error("[IGNIS] calidad de datos", error); caja.hidden = true; }
  }

  async function actualizarTodo() {
    cargarCalidad();
    await Promise.all([cargarRanking(), cargarCatalogo()]);
    if (iniciadas.has("pareto")) pareto.recargarSiCambio();
    if (iniciadas.has("mapa")) mapa.cargar();
    huecosCache = null; tierraCache = null;
    if (pestana === "huecos") pintarHuecos();
    if (pestana === "tierra") pintarTierra();
    fetch(`${API}/pareto?entorno=${entorno}`).then((r) => r.json()).then((d) => { frontera = d.frontera.length; pintarKpis(); }).catch(() => {});
  }

  async function sondear() {
    if (document.hidden || obtener("vista-investigaciones").hidden) return;
    try {
      const e = await pedir(`${API}/estado`);
      if (huella && e.huella && e.huella !== huella) {
        huella = e.huella;
        await actualizarTodo();
        avisar("Datos nuevos incorporados: el ranking, el Pareto y el mapa se actualizaron.");
      } else if (!huella) huella = e.huella ?? "";
    } catch { /* servidor ocupado: se reintenta en el siguiente ciclo */ }
  }

  // Datos de prueba (CSV) y demo guiada: tras importar o quitar se actualiza TODO al instante, sin esperar al sondeo.
  const prueba = crearPrueba({
    alCambiar: async (informe) => {
      await actualizarTodo();
      if (informe?.investigaciones_nuevas?.length) { seleccionar(informe.investigaciones_nuevas[0]); }
      avisar(informe ? "Datos de prueba cargados: ranking, Pareto, mapa y comparación ya los incluyen." : "Datos de prueba quitados.");
    },
  });
  const demo = crearDemo({
    boton: obtener("inv-demo-boton"),
    reducirMovimiento: () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    acciones: {
      irA: (t) => irA(t), seleccionar: (id) => seleccionar(id), fijarComparadas: (ids) => { comparadas = ids.slice(0, MAX_COMPARAR); pintarLista(); pintarBandeja(); if (pestana === "comparar") pintarComparar(); },
      cargarEjemplo: async () => {
        const r = await fetch(`${API}/prueba/plantilla`); const inf = await (await fetch(`${API}/prueba`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contenido: await r.text() }) })).json();
        huella = ""; await actualizarTodo(); return inf.investigaciones_nuevas ?? [];
      },
      quitarPrueba: async () => { await fetch(`${API}/prueba`, { method: "DELETE" }); await actualizarTodo(); },
      hayPrueba: () => prueba.activos > 0,
      sondearMapa: (o2, p) => mapa.sondear(o2, p),
      abrirMonitor: async () => { const d = await (await fetch("/api/v1/preset/lunar", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json(); opciones.alCargarEnMonitor?.(d.monitor); },
      fijarEntorno: (e) => { const b = /** @type {HTMLElement|null} */ (document.querySelector(`[data-inv-entorno="${e}"]`)); b?.click(); },
    },
  });

  // ------------------------------------------------------------------------------------------ eventos
  for (const boton of /** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-inv-entorno]"))) {
    boton.addEventListener("click", () => {
      entorno = String(boton.dataset.invEntorno);
      marcarEntorno(entorno, true);
      for (const b of document.querySelectorAll("[data-inv-entorno]")) b.setAttribute("aria-pressed", String(b === boton));
      cargarRanking();
      if (iniciadas.has("pareto")) pareto.entornoCambio();
      if (pestana === "tierra") pintarTierra();
    });
  }
  selArea.addEventListener("change", cargarRanking);
  selComb.addEventListener("change", cargarRanking);
  for (const [id, formato] of [["inv-export-csv", "csv"], ["inv-export-json", "json"]]) obtener(id).addEventListener("click", () => { window.location.href = `${API}/export?formato=${formato}`; });
  obtener("inv-export-anclas").addEventListener("click", () => { window.location.href = `${API}/export?formato=csv&conjunto=anclas`; });
  const tabs = /** @type {HTMLButtonElement[]} */ ([...document.querySelectorAll("[data-inv-tab]")]);
  for (const t of tabs) {
    t.addEventListener("click", () => irA(String(t.dataset.invTab)));
    t.addEventListener("keydown", (e) => {  // patrón WAI-ARIA tabs: flechas, Inicio y Fin
      const k = { ArrowRight: 1, ArrowLeft: -1 }[/** @type {"ArrowRight"} */ (e.key)];
      if (!k && e.key !== "Home" && e.key !== "End") return;
      e.preventDefault();
      const j = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (tabs.indexOf(t) + (k ?? 0) + tabs.length) % tabs.length;
      tabs[j].focus(); irA(String(tabs[j].dataset.invTab));
    });
  }
  setInterval(sondear, PERIODO_SONDEO_MS);

  return {
    /** Carga los datos la primera vez que se muestra la vista. */
    activar() {
      if (cargado) return;
      cargado = true;
      cargarRanking(); cargarCatalogo(); cargarCalidad();
      fetch(`${API}/pareto?entorno=luna`).then((r) => r.json()).then((d) => { frontera = d.frontera.length; pintarKpis(); }).catch(() => {});
      irA("analisis");
    },
  };
}
