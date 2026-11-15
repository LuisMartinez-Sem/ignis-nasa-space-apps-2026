// @ts-check
/**
 * Simulador de incidentes históricos: cronología humana real vs. reacción de IGNIS.
 * Regla de honestidad: nada se presenta como "N veces más rápido". Se muestra una
 * ventana de oportunidad, y cada hecho lleva su nivel de confianza y su fuente.
 * Todo texto externo entra con textContent; los enlaces solo admiten https.
 */
import { obtener } from "./dom.js";
import { COLOR_NIVEL } from "./paleta.js";

const NS = "http://www.w3.org/2000/svg";
const ETIQUETA_CONFIANZA = {
  documentado: "Documentado", aproximado: "Aproximado", no_verificado: "No verificado",
  ilustrativo: "Ilustrativo", modelo: "Modelo", supuesto: "Supuesto",
};
const ETIQUETA_TIPO = {
  deteccion_respuesta: "Detección y respuesta", precondicion: "Precondición",
  falsa_alarma: "Falsa alarma", validacion: "Validación",
};
const DURACION_REPRODUCCION_MS = 7000;

/**
 * Crea un elemento HTML con clase y texto seguro.
 * @param {string} etiqueta @param {string|null} [clase] @param {string|null} [texto]
 */
function h(etiqueta, clase = null, texto = null) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== null) nodo.textContent = texto;
  return nodo;
}

/** @param {string} etiqueta @param {Record<string, string|number>} atributos */
function s(etiqueta, atributos = {}) {
  const nodo = document.createElementNS(NS, etiqueta);
  for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, String(v));
  return nodo;
}

/** @param {number|null} t Segundos → texto legible. */
function formatearTiempo(t) {
  if (t === null || t === undefined) return "sin hora";
  if (t < 60) return `${t.toLocaleString("es-MX", { maximumFractionDigits: 1 })} s`;
  if (t < 3600) return `${(t / 60).toLocaleString("es-MX", { maximumFractionDigits: 1 })} min`;
  return `${(t / 3600).toLocaleString("es-MX", { maximumFractionDigits: 1 })} h`;
}

/** @param {string} confianza */
function insignia(confianza) {
  const el = h("span", "insignia", ETIQUETA_CONFIANZA[confianza] ?? confianza);
  el.dataset.confianza = confianza;
  return el;
}

/** Cifra principal por tipo de incidente: lo primero que debe leerse. @param {any} sim */
function cifraPrincipal(sim) {
  const m = sim.impacto.metricas;
  switch (sim.tipo) {
    case "deteccion_respuesta":
      return { valor: m.reaccion_ignis_s == null ? "—" : formatearTiempo(m.reaccion_ignis_s),
        pie: `reacción de IGNIS · el fuego duró ${formatearTiempo(m.ventana_min_s)}–${formatearTiempo(m.ventana_max_s)}` };
    case "falsa_alarma":
      return { valor: m.falsas_alarmas_ignis_pct == null ? "—" : `${m.falsas_alarmas_ignis_pct} %`,
        pie: `falsas alarmas de IGNIS · umbral simple: ${m.falsas_alarmas_umbral_simple_pct ?? "—"} %` };
    case "precondicion":
      return { valor: m.indice_riesgo == null ? "Fuera de dominio" : `${m.indice_riesgo}`,
        pie: m.indice_con_aire == null ? "sin índice: atmósfera fuera del dominio del modelo" : `índice de riesgo · con aire sería ${m.indice_con_aire}` };
    default:
      return { valor: m.error_abs_medio_pct == null ? "—" : `${m.error_abs_medio_pct} %`, pie: "error medio vs. medición (modelo sintético)" };
  }
}

/** Eje logarítmico: x = log10(1 + t). @param {number} t */
const escalaLog = (t) => Math.log10(1 + Math.max(0, t));

/**
 * Carrera en escala logarítmica: permite ver 0,7 s y 840 s en el mismo eje.
 * @param {any} sim
 * @returns {{ svg: SVGSVGElement, revelarHasta: (t: number) => void, tMax: number }}
 */
function dibujarCarrera(sim) {
  const ancho = 900, alto = 210, margen = { i: 96, d: 24, s: 24, b: 34 };
  const ventana = sim.impacto.metricas.ventana_min_s != null
    ? [sim.impacto.metricas.ventana_min_s, sim.impacto.metricas.ventana_max_s] : null;
  const tiempos = [...sim.timeline_humano, ...sim.timeline_ignis].map((e) => e.t_s).filter((t) => t !== null);
  const tMax = Math.max(10, ...tiempos, ventana?.[1] ?? 0) * 1.15;
  const x = (/** @type {number} */ t) => margen.i + (escalaLog(t) / escalaLog(tMax)) * (ancho - margen.i - margen.d);
  const yH = 78, yI = 150;
  const svg = /** @type {SVGSVGElement} */ (s("svg", { viewBox: `0 0 ${ancho} ${alto}`, role: "img", class: "carrera",
    "aria-label": "Línea de tiempo en escala logarítmica: eventos humanos arriba, reacción de IGNIS abajo" }));

  for (const t of [0, 1, 10, 60, 600, 3600, 36000].filter((v) => v <= tMax)) {
    svg.append(s("line", { x1: x(t), x2: x(t), y1: margen.s, y2: alto - margen.b, class: "carrera-rejilla" }));
    const txt = s("text", { x: x(t), y: alto - 12, class: "carrera-eje", "text-anchor": "middle" });
    txt.textContent = t === 0 ? "0" : formatearTiempo(t);
    svg.append(txt);
  }
  for (const [y, nombre] of [[yH, "HUMANO"], [yI, "IGNIS"]]) {
    svg.append(s("line", { x1: margen.i, x2: ancho - margen.d, y1: y, y2: y, class: "carrera-carril", "data-carril": nombre }));
    const rot = s("text", { x: 12, y: y + 4, class: "carrera-rotulo", "data-carril": nombre });
    rot.textContent = nombre;
    svg.append(rot);
  }
  /** @type {{ el: SVGElement, t: number }[]} */ const revelables = [];
  if (ventana) {
    const banda = s("rect", { x: x(ventana[0]), y: yH - 16, width: Math.max(2, x(ventana[1]) - x(ventana[0])), height: 32, class: "carrera-ventana" });
    const titulo = s("title");
    titulo.textContent = `Ventana de oportunidad: ${formatearTiempo(ventana[0])} – ${formatearTiempo(ventana[1])}`;
    banda.append(titulo);
    svg.append(banda);
    revelables.push({ el: banda, t: 0 });
  }
  /** @param {any[]} eventos @param {number} y @param {string} carril */
  const marcar = (eventos, y, carril) => {
    for (const e of eventos) {
      if (e.t_s === null) continue;
      const marca = s("circle", { cx: x(e.t_s), cy: y, r: 6, class: "carrera-marca", "data-carril": carril, "data-confianza": e.confianza ?? "modelo", tabindex: 0 });
      const titulo = s("title");
      titulo.textContent = `${formatearTiempo(e.t_s)} · ${e.accion}`;
      marca.append(titulo);
      svg.append(marca);
      revelables.push({ el: marca, t: e.t_s });
    }
  };
  marcar(sim.timeline_humano, yH, "humano");
  marcar(sim.timeline_ignis, yI, "ignis");
  const cabezal = s("line", { x1: x(0), x2: x(0), y1: margen.s - 6, y2: alto - margen.b, class: "carrera-cabezal" });
  svg.append(cabezal);

  return {
    svg, tMax,
    revelarHasta(t) {
      const px = x(t);
      cabezal.setAttribute("x1", String(px));
      cabezal.setAttribute("x2", String(px));
      for (const { el, t: te } of revelables) el.classList.toggle("oculto", te > t);
    },
  };
}

/** Serie del índice de riesgo (si el incidente la trae). @param {any} serie */
function dibujarSerie(serie) {
  const ancho = 900, alto = 120;
  const svg = /** @type {SVGSVGElement} */ (s("svg", { viewBox: `0 0 ${ancho} ${alto}`, role: "img", class: "serie",
    "aria-label": "Índice de riesgo de IGNIS a lo largo del evento" }));
  const tMax = Math.max(1, serie[serie.length - 1].t_s);
  const x = (/** @type {number} */ t) => 40 + (t / tMax) * (ancho - 56);
  const y = (/** @type {number} */ v) => alto - 18 - (v / 100) * (alto - 30);
  for (const g of [25, 50, 75]) svg.append(s("line", { x1: 40, x2: ancho - 16, y1: y(g), y2: y(g), class: "carrera-rejilla" }));
  svg.append(s("polyline", { points: serie.map((/** @type {any} */ p) => `${x(p.t_s)},${y(p.indice_riesgo)}`).join(" "), class: "serie-linea" }));
  serie.forEach((/** @type {any} */ p, i) => {
    if (i % Math.max(1, Math.floor(serie.length / 24)) !== 0) return;
    const [r, g, b] = COLOR_NIVEL[p.nivel] ?? COLOR_NIVEL.NOMINAL;
    svg.append(s("circle", { cx: x(p.t_s), cy: y(p.indice_riesgo), r: 3, fill: `rgb(${r},${g},${b})` }));
  });
  const etiqueta = s("text", { x: 40, y: 12, class: "carrera-eje" });
  etiqueta.textContent = "Índice de riesgo (0–100) · telemetría ilustrativa";
  svg.append(etiqueta);
  return svg;
}

/** @param {any[]} eventos @param {string} titulo @param {string} clase */
function columnaTimeline(eventos, titulo, clase) {
  const col = h("section", `timeline ${clase}`);
  col.append(h("h4", "timeline-titulo", titulo));
  const ol = h("ol", "timeline-lista");
  for (const e of eventos) {
    const li = h("li", "timeline-item");
    li.dataset.confianza = e.confianza ?? "modelo";
    const t = h("span", "timeline-t mono", formatearTiempo(e.t_s));
    const cuerpo = h("div", "timeline-cuerpo");
    cuerpo.append(h("p", "timeline-accion", e.accion));
    if (e.resultado) cuerpo.append(h("p", "timeline-resultado", e.resultado));
    const pie = h("div", "timeline-pie");
    pie.append(insignia(e.confianza ?? "modelo"));
    if (e.fuente != null) pie.append(h("span", "fuente-ref mono", `[${e.fuente}]`));
    cuerpo.append(pie);
    li.append(t, cuerpo);
    ol.append(li);
  }
  col.append(ol);
  return col;
}

/** @param {any} f */
function itemFuente(f) {
  const li = h("li", "fuente");
  li.append(h("span", "fuente-ref mono", `[${f.id}]`));
  const cuerpo = h("div");
  const titulo = typeof f.url === "string" && f.url.startsWith("https://") ? h("a", null, f.titulo) : h("span", null, f.titulo);
  if (titulo instanceof HTMLAnchorElement) {
    titulo.href = f.url;
    titulo.rel = "noopener noreferrer";
    titulo.target = "_blank";
  }
  cuerpo.append(titulo, h("span", "fuente-org", ` — ${f.organizacion}`));
  const fiab = h("span", "insignia", `fiabilidad ${f.fiabilidad}`);
  fiab.dataset.fiabilidad = f.fiabilidad;
  cuerpo.append(" ", fiab);
  if (f.nota) cuerpo.append(h("p", "fuente-nota", f.nota));
  li.append(cuerpo);
  return li;
}

export function crearIncidentes() {
  const lista = obtener("incidentes-lista");
  const detalle = obtener("incidentes-detalle");
  /** @type {number} */ let animacion = 0;
  let cargado = false;
  let seleccion = "";

  /** Formulario para agregar un incidente propio (IGNIS evalúa su atmósfera; todo queda marcado como no verificado). */
  function montarFormulario() {
    if (document.getElementById("inc-form")) return;
    const det = h("details", "inc-form"); det.id = "inc-form";
    det.append(h("summary", null, "＋ Agregar un incidente propio"));
    const f = /** @type {HTMLFormElement} */ (h("form", "inc-form-cuerpo"));
    const campo = (/** @type {string} */ id, /** @type {string} */ etq, /** @type {string} */ tipo, /** @type {Record<string,string>} */ extra = {}) => {
      const l = h("label", "inc-campo"), i = /** @type {HTMLInputElement} */ (tipo === "textarea" ? h("textarea") : h("input"));
      if (tipo !== "textarea") i.type = tipo; i.name = id; for (const [k, v] of Object.entries(extra)) i.setAttribute(k, v);
      l.append(h("span", null, etq), i); f.append(l); return i;
    };
    campo("nombre", "Nombre", "text", { required: "", maxlength: "80" });
    campo("fecha", "Fecha (opcional)", "text", { maxlength: "30", placeholder: "p. ej. 1997-02-23" });
    campo("lugar", "Lugar", "text", { required: "", maxlength: "120" });
    campo("resumen", "Qué ocurrió", "textarea", { required: "", minlength: "10", maxlength: "800", rows: "3" });
    campo("o2", "O₂ de la atmósfera (%)", "number", { required: "", min: "10", max: "100", step: "0.1", value: "21" });
    campo("p", "Presión (kPa)", "number", { required: "", min: "10", max: "250", step: "0.1", value: "101.3" });
    campo("fuente", "Fuente de la información (obligatoria)", "text", { required: "", maxlength: "200" });
    campo("eventos", "Cronología (una línea por hecho: segundos | descripción)", "textarea", { rows: "3", placeholder: "0 | Se detecta humo\n40 | La tripulación aplica el extintor" });
    const grav = /** @type {HTMLSelectElement} */ (h("select")); grav.name = "grav";
    for (const [v, n] of [["microgravedad", "Microgravedad"], ["1g", "1 g (Tierra)"]]) { const o = h("option", null, n); o.value = v; grav.append(o); }
    const lg = h("label", "inc-campo"); lg.append(h("span", null, "Gravedad"), grav); f.append(lg);
    const msg = h("p", "inv-nota"); msg.setAttribute("role", "status");
    const enviar = /** @type {HTMLButtonElement} */ (h("button", "boton", "Agregar")); enviar.type = "submit";
    f.append(enviar, msg);
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const v = (/** @type {string} */ n) => /** @type {HTMLInputElement} */ (f.elements.namedItem(n)).value.trim();
      const eventos = v("eventos").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [t, ...r] = l.split("|"); const n = Number(t.replace(",", ".")); return r.length && Number.isFinite(n) ? { t_s: n, accion: r.join("|").trim() } : { t_s: null, accion: l }; });
      const cuerpo = { nombre: v("nombre"), fecha: v("fecha"), lugar: v("lugar"), resumen: v("resumen"), regimen_gravedad: grav.value, fraccion_o2: Number(v("o2")) / 100, presion_kpa: Number(v("p")), fuente: v("fuente"), eventos };
      msg.textContent = "Agregando…";
      try {
        const r = await fetch("/api/v1/incidentes/propio", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail?.[0]?.msg ?? "Revisa los datos (O₂ 10-100 %, presión 10-250 kPa).");
        const nuevo = await r.json(); f.reset(); msg.textContent = "Incidente agregado; aparece marcado como «Propio» y «no verificado».";
        await cargarLista(); seleccionar(nuevo.id);
      } catch (e) { msg.textContent = `No se pudo agregar: ${e instanceof Error ? e.message : "error"}`; }
    });
    det.append(f);
    lista.insertAdjacentElement("afterend", det);
  }

  async function cargarLista() {
    montarFormulario();
    try {
      const r = await fetch("/api/v1/incidentes");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      /** @type {any[]} */ const incidentes = await r.json();
      lista.replaceChildren(
        ...incidentes.map((i) => {
          const li = h("li");
          const boton = /** @type {HTMLButtonElement} */ (h("button", "incidente-tarjeta"));
          boton.type = "button";
          boton.dataset.id = i.id;
          boton.setAttribute("aria-pressed", "false");
          boton.append(h("span", "incidente-fecha mono", i.fecha), h("strong", null, i.nombre),
            h("span", "incidente-tipo", ETIQUETA_TIPO[i.tipo] ?? i.tipo));
          if (!i.modelo_aplicable) {
            const fuera = h("span", "insignia", "Fuera de dominio");
            fuera.dataset.confianza = "no_verificado";
            boton.append(fuera);
          }
          boton.addEventListener("click", () => seleccionar(i.id));
          li.append(boton);
          if (i.propio) {
            const etiqueta = h("span", "insignia", "Propio"); etiqueta.dataset.confianza = "supuesto"; boton.append(etiqueta);
            const quitar = /** @type {HTMLButtonElement} */ (h("button", "boton boton-sec incidente-quitar", "Quitar")); quitar.type = "button";
            quitar.setAttribute("aria-label", `Quitar el incidente propio ${i.nombre}`);
            quitar.addEventListener("click", async () => {
              const r = await fetch(`/api/v1/incidentes/propio/${encodeURIComponent(i.id)}`, { method: "DELETE" });
              if (r.ok) { if (seleccion === i.id) seleccion = ""; cargarLista(); }
            });
            li.append(quitar);
          }
          return li;
        }),
      );
      cargado = true;
      if (incidentes[0]) seleccionar(incidentes.find((i) => i.id === "mir-1997")?.id ?? incidentes[0].id);
    } catch (error) {
      lista.replaceChildren(h("li", "vacio", "No se pudo cargar el catálogo de incidentes."));
      console.error("[IGNIS] incidentes", error);
    }
  }

  /** @param {string} id */
  async function seleccionar(id) {
    seleccion = id;
    cancelAnimationFrame(animacion);
    for (const b of lista.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.id === id));
    detalle.setAttribute("aria-busy", "true");
    detalle.replaceChildren(h("p", "vacio", "Simulando…"));
    try {
      const r = await fetch(`/api/v1/incidentes/${encodeURIComponent(id)}/simular`);
      if (r.status === 503) {
        detalle.replaceChildren(h("p", "vacio", "El detector temporal aún se está cargando. Reintentando…"));
        setTimeout(() => seleccion === id && seleccionar(id), 3000);
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (seleccion === id) pintar(await r.json());
    } catch (error) {
      detalle.replaceChildren(h("p", "error", "No se pudo simular este incidente."));
      console.error("[IGNIS] simular", error);
    } finally {
      detalle.setAttribute("aria-busy", "false");
    }
  }

  /** @param {any} sim */
  function pintar(sim) {
    const cifra = cifraPrincipal(sim);
    const cab = h("header", "inc-cabecera");
    const titulos = h("div");
    titulos.append(h("h3", "inc-titulo", sim.nombre), h("p", "inc-sub", ETIQUETA_TIPO[sim.tipo] ?? sim.tipo));
    const cuadro = h("div", "inc-cifra");
    cuadro.append(h("span", "inc-cifra-valor mono", cifra.valor), h("span", "inc-cifra-pie", cifra.pie));
    if (sim.impacto.es_contrafactual) cuadro.append(h("span", "etiqueta", "CONTRAFACTUAL · no medido"));
    cab.append(titulos, cuadro);

    const partes = [cab];
    if (sim.advertencia_modelo) {
      const aviso = h("p", "inc-aviso", sim.advertencia_modelo);
      aviso.setAttribute("role", "note");
      partes.push(aviso);
    }
    partes.push(h("p", "inc-resumen", sim.impacto.resumen));

    if (sim.tipo === "deteccion_respuesta") {
      const carrera = dibujarCarrera(sim);
      const controles = h("div", "inc-controles");
      const reproducir = /** @type {HTMLButtonElement} */ (h("button", "boton", "▶ Reproducir"));
      reproducir.type = "button";
      const barra = /** @type {HTMLInputElement} */ (h("input"));
      barra.type = "range"; barra.min = "0"; barra.max = "1000"; barra.value = "1000";
      barra.setAttribute("aria-label", "Posición en la línea de tiempo");
      const aplicar = () => carrera.revelarHasta(Math.pow(10, (Number(barra.value) / 1000) * escalaLog(carrera.tMax)) - 1);
      barra.addEventListener("input", () => { cancelAnimationFrame(animacion); aplicar(); });
      reproducir.addEventListener("click", () => {
        cancelAnimationFrame(animacion);
        const reducir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const inicio = performance.now();
        const paso = (/** @type {number} */ ahora) => {
          const f = reducir ? 1 : Math.min(1, (ahora - inicio) / DURACION_REPRODUCCION_MS);
          barra.value = String(Math.round(f * 1000));
          aplicar();
          if (f < 1) animacion = requestAnimationFrame(paso);
        };
        animacion = requestAnimationFrame(paso);
      });
      controles.append(reproducir, barra);
      const marco = h("figure", "inc-figura");
      marco.append(carrera.svg, controles);
      partes.push(marco);
      aplicar();
    }
    if (sim.serie_riesgo?.length > 1) {
      const fig = h("figure", "inc-figura");
      fig.append(dibujarSerie(sim.serie_riesgo));
      partes.push(fig);
    }

    const dos = h("div", "inc-columnas");
    if (sim.timeline_humano.length) dos.append(columnaTimeline(sim.timeline_humano, "Lo que ocurrió (documentado)", "timeline-humano"));
    dos.append(columnaTimeline(sim.timeline_ignis, sim.tipo === "validacion" ? "Predicción de IGNIS por experimento" : "Lo que haría IGNIS", "timeline-ignis"));
    partes.push(dos);

    const metodo = h("section", "inc-bloque");
    metodo.append(h("h4", null, "Metodología"), h("p", null, sim.impacto.metodologia));
    const supuestos = h("section", "inc-bloque");
    supuestos.append(h("h4", null, "Supuestos y límites"));
    const ul = h("ul", "inc-supuestos");
    for (const texto of sim.supuestos) ul.append(h("li", null, texto));
    supuestos.append(ul);
    const fuentes = h("section", "inc-bloque");
    fuentes.append(h("h4", null, `Fuentes (${sim.fuentes.length})`));
    const ulf = h("ul", "fuentes");
    for (const f of sim.fuentes) ulf.append(itemFuente(f));
    fuentes.append(ulf);
    partes.push(metodo, supuestos, fuentes);
    detalle.replaceChildren(...partes);
  }

  return {
    /** Carga el catálogo la primera vez que se abre la pestaña. */
    activar() {
      if (!cargado) cargarLista();
    },
  };
}
