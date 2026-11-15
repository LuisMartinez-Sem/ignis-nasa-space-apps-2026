// @ts-check
/**
 * Panel de notas del investigador notas por investigación, notas generales, lista de tareas y exportación a TXT.
 * Todo se guarda en localStorage de este navegador (nunca sale del equipo). Las funciones de datos son puras y se prueban en Node.
 */
import { h, obtener } from "./dom.js";

export const CLAVE = "ignis-notas-v2";

/** @typedef {{ id: string, texto: string, hecha: boolean }} Tarea */
/** @typedef {{ general: string, porInv: Record<string, string>, tareas: Tarea[], sembrado: boolean }} Estado */

/** Tareas de ejemplo que se siembran una sola vez (editables y borrables). */
export const TAREAS_INICIALES = ["Confirmar O₂ de Saffire-I con PSI", "Revisar la presión de las pruebas de Saffire-IV", "Pedir validación de un especialista"];

/** @returns {Estado} */
export const estadoVacio = () => ({ general: "", porInv: {}, tareas: [], sembrado: false });

/** Lee un estado guardado tolerando datos corruptos. @param {string|null} crudo @returns {Estado} */
export function leerEstado(crudo) {
  const e = estadoVacio();
  try {
    const d = crudo ? JSON.parse(crudo) : null;
    if (!d || typeof d !== "object") return e;
    if (typeof d.general === "string") e.general = d.general.slice(0, 20000);
    if (d.porInv && typeof d.porInv === "object") for (const [k, v] of Object.entries(d.porInv)) if (typeof v === "string" && v.trim()) e.porInv[k] = v.slice(0, 20000);
    if (Array.isArray(d.tareas)) e.tareas = d.tareas.filter((/** @type {any} */ t) => t && typeof t.texto === "string").slice(0, 200)
      .map((/** @type {any} */ t, /** @type {number} */ i) => ({ id: String(t.id ?? i), texto: t.texto.slice(0, 300), hecha: t.hecha === true }));
    e.sembrado = d.sembrado === true;
  } catch { /* guardado ilegible: se empieza vacío */ }
  return e;
}

/** @param {Estado} e @returns {Estado} */
export function sembrar(e) {
  if (e.sembrado) return e;
  return { ...e, sembrado: true, tareas: [...TAREAS_INICIALES.map((texto, i) => ({ id: `ini${i}`, texto, hecha: false })), ...e.tareas] };
}

/** Texto plano para exportar. @param {Estado} e @param {(id: string) => string} nombre @param {string} [fecha] */
export function aTxt(e, nombre, fecha = new Date().toISOString().slice(0, 10)) {
  const L = [`IGNIS — Notas del investigador (${fecha})`, ""];
  L.push("TAREAS", ...(e.tareas.length ? e.tareas.map((t) => `[${t.hecha ? "x" : " "}] ${t.texto}`) : ["(sin tareas)"]), "");
  L.push("NOTAS GENERALES", e.general.trim() || "(vacío)", "");
  const ids = Object.keys(e.porInv).filter((k) => e.porInv[k].trim());
  L.push("NOTAS POR INVESTIGACIÓN");
  if (!ids.length) L.push("(vacío)");
  for (const id of ids) L.push(`— ${nombre(id)}:`, e.porInv[id].trim(), "");
  return L.join("\n") + "\n";
}

/** Cuenta de tareas pendientes. @param {Estado} e */
export const pendientes = (e) => e.tareas.filter((t) => !t.hecha).length;

/**
 * @param {{ boton: HTMLElement, seleccion: () => string, nombre: (id: string) => string, ir: (id: string) => void }} o
 */
export function crearNotas(o) {
  /** @type {Storage|null} */ let almacen = null;
  try { almacen = localStorage; } catch { /* sin almacenamiento: las notas viven solo mientras la página esté abierta */ }
  let estado = sembrar(leerEstado(almacen?.getItem(CLAVE) ?? null));
  const guardar = () => { try { almacen?.setItem(CLAVE, JSON.stringify(estado)); } catch { /* cuota o modo privado */ } };

  const panel = h("aside", "notas-panel"); panel.id = "panel-notas"; panel.hidden = true;
  panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Notas del investigador");
  const cab = h("div", "notas-cab"); const cerrar = /** @type {HTMLButtonElement} */ (h("button", "boton", "Cerrar")); cerrar.type = "button";
  cab.append(h("strong", null, "Notas del investigador"), cerrar);

  // Investigación seleccionada
  const etqInv = h("label", "inv-etq"); etqInv.htmlFor = "notas-inv";
  const taInv = /** @type {HTMLTextAreaElement} */ (h("textarea", "notas-area")); taInv.id = "notas-inv"; taInv.rows = 5; taInv.maxLength = 20000;
  taInv.placeholder = "Qué comprobaste, qué falta, de dónde sale el dato…";
  taInv.addEventListener("input", () => { const id = o.seleccion(); if (!id) return; if (taInv.value.trim()) estado.porInv[id] = taInv.value; else delete estado.porInv[id]; guardar(); pintarOtras(); });
  const otras = h("ul", "notas-otras");

  // General
  const etqGen = h("label", "inv-etq", "Notas generales"); etqGen.htmlFor = "notas-gen";
  const taGen = /** @type {HTMLTextAreaElement} */ (h("textarea", "notas-area")); taGen.id = "notas-gen"; taGen.rows = 4; taGen.maxLength = 20000;
  taGen.addEventListener("input", () => { estado.general = taGen.value; guardar(); });

  // Tareas
  const tareas = h("ul", "notas-tareas");
  const entrada = /** @type {HTMLInputElement} */ (h("input", "notas-entrada")); entrada.type = "text"; entrada.maxLength = 300; entrada.placeholder = "Nueva tarea…"; entrada.setAttribute("aria-label", "Nueva tarea");
  const añadirB = /** @type {HTMLButtonElement} */ (h("button", "boton", "Añadir")); añadirB.type = "button";
  const añadir = () => { const t = entrada.value.trim(); if (!t) return; estado.tareas.push({ id: `t${Date.now()}${estado.tareas.length}`, texto: t, hecha: false }); entrada.value = ""; guardar(); pintarTareas(); };
  añadirB.addEventListener("click", añadir);
  entrada.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); añadir(); } });
  const fila = h("div", "notas-fila"); fila.append(entrada, añadirB);

  // Pie: verificación + exportar
  const chk = /** @type {HTMLInputElement} */ (h("input")); chk.type = "checkbox"; chk.id = "notas-ver";
  const etqChk = h("label", "notas-ver", " Mostrar las notas de verificación y limitaciones en pantalla"); etqChk.htmlFor = "notas-ver"; etqChk.prepend(chk);
  chk.addEventListener("change", () => { document.body.classList.toggle("ver-notas", chk.checked); try { almacen?.setItem("ignis-notas", chk.checked ? "1" : "0"); } catch { /* opcional */ } });
  const exportar = /** @type {HTMLButtonElement} */ (h("button", "boton", "Exportar a TXT")); exportar.type = "button";
  exportar.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([aTxt(estado, o.nombre)], { type: "text/plain;charset=utf-8" }));
    const a = h("a"); /** @type {HTMLAnchorElement} */ (a).href = url; /** @type {HTMLAnchorElement} */ (a).download = `ignis-notas-${new Date().toISOString().slice(0, 10)}.txt`;
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  const nota = h("p", "inv-nota", "Se guardan solo en este navegador. Exporta a TXT para llevártelas.");

  panel.append(cab, etqInv, taInv, h("span", "inv-etq", "Otras investigaciones con nota"), otras, h("span", "inv-etq", "Tareas"), tareas, fila, etqGen, taGen, etqChk, exportar, nota);
  document.body.append(panel);

  function pintarTareas() {
    tareas.replaceChildren(...estado.tareas.map((t) => {
      const li = h("li", "notas-tarea"); li.dataset.hecha = String(t.hecha);
      const c = /** @type {HTMLInputElement} */ (h("input")); c.type = "checkbox"; c.checked = t.hecha; c.setAttribute("aria-label", t.texto);
      c.addEventListener("change", () => { t.hecha = c.checked; guardar(); pintarTareas(); });
      const q = /** @type {HTMLButtonElement} */ (h("button", "notas-quitar", "×")); q.type = "button"; q.setAttribute("aria-label", `Quitar tarea: ${t.texto}`);
      q.addEventListener("click", () => { estado.tareas = estado.tareas.filter((x) => x !== t); guardar(); pintarTareas(); });
      li.append(c, h("span", null, t.texto), q); return li;
    }));
    if (!estado.tareas.length) tareas.append(h("li", "inv-nota", "Sin tareas."));
    actualizarBoton();
  }
  function pintarOtras() {
    const sel = o.seleccion();
    const ids = Object.keys(estado.porInv).filter((k) => k !== sel);
    otras.replaceChildren(...ids.map((id) => {
      const li = h("li"); const b = /** @type {HTMLButtonElement} */ (h("button", "chip-inv", o.nombre(id))); b.type = "button"; b.title = estado.porInv[id].slice(0, 200);
      b.addEventListener("click", () => { o.ir(id); }); li.append(b); return li;
    }));
    if (!ids.length) otras.append(h("li", "inv-nota", "Ninguna todavía."));
    actualizarBoton();
  }
  function actualizarBoton() {
    const n = pendientes(estado), c = Object.keys(estado.porInv).length;
    o.boton.textContent = n || c ? `Notas · ${n} tarea${n === 1 ? "" : "s"}${c ? ` · ${c} nota${c === 1 ? "" : "s"}` : ""}` : "Notas";
  }
  /** Sincroniza el cuadro con la investigación seleccionada (sin pisar lo que se está escribiendo). */
  function cambioSeleccion() {
    const id = o.seleccion();
    etqInv.textContent = id ? `Nota de la investigación seleccionada: ${o.nombre(id)}` : "Selecciona una investigación para anotarla";
    taInv.disabled = !id; taInv.value = id ? (estado.porInv[id] ?? "") : "";
    pintarOtras();
  }
  function abrir(ver = panel.hidden) {
    panel.hidden = !ver; o.boton.setAttribute("aria-pressed", String(ver));
    if (ver) { chk.checked = document.body.classList.contains("ver-notas"); taGen.value = estado.general; cambioSeleccion(); pintarTareas(); (taInv.disabled ? taGen : taInv).focus(); }
    else o.boton.focus();
  }
  o.boton.setAttribute("aria-haspopup", "dialog"); o.boton.setAttribute("aria-pressed", "false");
  o.boton.addEventListener("click", () => abrir());
  cerrar.addEventListener("click", () => abrir(false));
  panel.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); abrir(false); } });
  pintarTareas(); guardar();
  return { cambioSeleccion, abrir, get abierto() { return !panel.hidden; } };
}
