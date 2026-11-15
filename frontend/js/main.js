// @ts-check
/** Punto de entrada del HUD 3.0: monitor (gemelo 3D + detector + copiloto) e incidentes. */
import { crearAudio } from "./audio.js";
import { NucleoAnillos } from "./anillos.js";
import { crearCajaNegra } from "./cajanegra.js";
import { crearControles } from "./controles.js";
import { crearCopiloto } from "./copilot.js";
import { crearPanelDetector } from "./detector.js";
import { obtener } from "./dom.js";
import { crearHardware } from "./hardware.js";
import { crearContexto } from "./contexto.js";
import { crearHud } from "./hud.js";
import { crearIncidentes } from "./incidents.js";
import { crearInvestigaciones } from "./investigaciones.js";
import { construirMensajes, hayEvento } from "./mensajes.js";
import { normalizarNivel, TEXTO_NIVEL } from "./paleta.js";
import { crearReproductor } from "./reproductor.js";
import { ClienteTiempoReal, obtenerBaseWs } from "./ws.js";

const RUTA_ESCENARIO = "/ws/demo?ritmo_hz=2";
const RUTA_MANUAL = "/ws/predict";
/** Escalas fijas del detector (src/senales.py::ESCALAS): normalizan los canales para la sonificación. */
const ESCALAS_CANALES = [200, 0.2, 0.3, 0.5, 0.2, 100];
const UMBRAL_CONTRASTE_VISIBLE_K = 900; // por debajo la llama no emite luz visible apreciable
const reducirMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** El gemelo 3D es opcional: sin WebGL el resto del HUD sigue funcionando. */
async function iniciarGemelo() {
  const lienzo = /** @type {HTMLCanvasElement} */ (obtener("lienzo-gemelo"));
  try {
    const { crearEscena, webglDisponible } = await import("./scene.js");
    if (!webglDisponible()) throw new Error("WebGL no disponible");
    return crearEscena(lienzo, { reducirMovimiento });
  } catch (error) {
    console.error("[IGNIS] Gemelo 3D no disponible", error);
    obtener("gemelo-fallback").hidden = false;
    return null;
  }
}

function iniciarVisionGemelo(/** @type {Awaited<ReturnType<typeof iniciarGemelo>>} */ gemelo) {
  const botones = /** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-vision]"));
  const divisor = obtener("divisor");
  const deslizador = /** @type {HTMLInputElement} */ (obtener("ctl-division"));
  /** @param {"visible"|"ir"|"dividido"} modo */
  const fijar = (modo) => {
    for (const b of botones) b.setAttribute("aria-pressed", String(b.dataset.vision === modo));
    document.body.dataset.vision = modo;
    divisor.hidden = modo !== "dividido";
    gemelo?.fijarVision(modo);
  };
  const mover = () => {
    const fraccion = Number(deslizador.value) / 100;
    divisor.style.setProperty("--division", `${fraccion * 100}%`);
    gemelo?.fijarDivision(fraccion);
  };
  for (const b of botones) b.addEventListener("click", () => fijar(/** @type {any} */ (b.dataset.vision)));
  deslizador.addEventListener("input", mover);
  obtener("boton-camara").addEventListener("click", () => gemelo?.reiniciarCamara());
  mover();
  fijar("visible");
}

function iniciarPestanas(/** @type {{ activar: () => void }} */ incidentes, /** @type {{ activar: () => void }} */ investigaciones) {
  const pestanas = /** @type {HTMLButtonElement[]} */ ([...document.querySelectorAll(".pestana")]);
  /** @param {string} vista */
  const mostrar = (vista) => {
    document.body.dataset.vista = vista;
    for (const p of pestanas) {
      const activa = p.dataset.vista === vista;
      p.setAttribute("aria-selected", String(activa));
      p.tabIndex = activa ? 0 : -1;
      obtener(`vista-${p.dataset.vista}`).hidden = !activa;
    }
    obtener("pie-monitor").hidden = vista !== "monitor"; // el historial del índice solo pertenece al Monitor
    if (vista === "incidentes") incidentes.activar();
    if (vista === "investigaciones") investigaciones.activar();
  };
  mostrar("investigaciones");
  for (const p of pestanas) {
    p.addEventListener("click", () => mostrar(String(p.dataset.vista)));
    // Teclado: flechas entre pestañas (patrón WAI-ARIA tabs)
    p.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const siguiente = pestanas[(pestanas.indexOf(p) + (e.key === "ArrowRight" ? 1 : -1) + pestanas.length) % pestanas.length];
      siguiente.focus();
      mostrar(String(siguiente.dataset.vista));
    });
  }
  return mostrar;
}

/** Badge "Validación pendiente": se activa a "Validado por …" cuando validacion.json trae un validador. */
async function iniciarValidacion() {
  const chip = obtener("chip-validacion");
  try {
    const r = await fetch("/validacion.json", { cache: "no-store" });
    if (!r.ok) return;
    const v = await r.json();
    if (v?.validador && typeof v.validador === "string") {
      chip.dataset.estado = "validado";
      chip.textContent = `Validado por ${v.validador.slice(0, 60)}`;
      chip.title = "Revisión externa registrada en docs/validacion_externa.md";
    }
  } catch { /* sin archivo: se queda en "pendiente" */ }
}

/** Estado inicial de las notas de verificación (ocultas por defecto). El botón «Notas» abre ahora el panel de notas (js/notas.js), que contiene el interruptor. */
function iniciarNotas() {
  let inicial = false;
  try { inicial = localStorage.getItem("ignis-notas") === "1"; } catch { /* sin almacenamiento: se queda oculto */ }
  document.body.classList.toggle("ver-notas", inicial);
}

async function iniciar() {
  iniciarNotas();
  const hud = crearHud();
  const contexto = crearContexto();
  const audio = crearAudio();
  const copiloto = crearCopiloto();
  const panelDetector = crearPanelDetector();
  const incidentes = crearIncidentes();
  const nucleo = new NucleoAnillos(/** @type {HTMLCanvasElement} */ (obtener("lienzo-nucleo")), {
    alSuavizar: hud.mostrarIndiceSuavizado,
  });
  // El preset lunar (u otro) se inyecta TAL CUAL en el Monitor: sliders, modo manual y cambio de pestaña.
  /** @type {(monitor: { sliders: Record<string, number|boolean> }) => void} */
  let cargarEnMonitor = () => {};
  const mostrarVista = iniciarPestanas(incidentes, crearInvestigaciones({ alCargarEnMonitor: (monitor) => cargarEnMonitor(monitor) }));

  const gemelo = await iniciarGemelo();
  iniciarVisionGemelo(gemelo);

  const cajaNegra = crearCajaNegra({ boton: /** @type {HTMLButtonElement} */ (obtener("boton-caja-negra")) });

  // --- Audio (apagado por defecto: requiere gesto del usuario) ---
  const botonAudio = obtener("boton-audio");
  botonAudio.addEventListener("click", async () => {
    const activo = await audio.fijar(!audio.activo);
    botonAudio.setAttribute("aria-pressed", String(activo));
    botonAudio.textContent = activo ? "Audio: on" : "Audio: off";
  });

  // --- Evaluación de riesgo (escenario o manual) ---
  // (cargarEnMonitor se asigna tras crear los controles)
  const cliente = new ClienteTiempoReal(obtenerBaseWs());
  /** @type {"escenario"|"manual"} */
  let modo = "escenario";
  let pFriaDetector = 0;
  let pFriaEvaluacion = 0;
  let ultimoEstadoEscena = { flujoCmS: 10, tReaccionK: /** @type {number|null} */ (null) };

  const controles = crearControles({
    alCambiarModo: (nuevo) => {
      modo = nuevo;
      cliente.conectar(nuevo === "manual" ? RUTA_MANUAL : RUTA_ESCENARIO);
    },
    alCambiarCondiciones: (condiciones) => {
      if (modo === "manual") cliente.enviar(condiciones);
    },
  });

  // Hardware: con termopar (campo «reaccion») y la casilla activa, la temperatura mueve el control T reacción del gemelo.
  crearHardware({
    alAbrir: () => { mostrarVista("monitor"); setTimeout(() => obtener("panel-hardware").scrollIntoView({ behavior: reducirMovimiento ? "auto" : "smooth", block: "center" }), 80); },
    alLecturaReaccion: (tempK) => {
      const t = Math.min(1500, Math.max(250, Math.round(tempK / 10) * 10));
      controles.establecerModo("manual");
      controles.aplicar({ "ctl-temp": t, "ctl-termopar": true });
    },
  });

  // Escenarios rápidos: un clic carga la atmósfera en el modo manual (el resto de controles se conserva).
  const ESCENARIOS = /** @type {Record<string, Record<string, number>>} */ ({
    iss: { "ctl-o2": 21, "ctl-presion": 101.3, "ctl-flujo": 10 },
    luna: { "ctl-o2": 30, "ctl-presion": 70.3, "ctl-flujo": 10 },
    marte: { "ctl-o2": 30, "ctl-presion": 70.3, "ctl-flujo": 10 },
    limite: { "ctl-o2": 40, "ctl-presion": 35, "ctl-flujo": 10 },
  });
  const botonesEscenario = /** @type {HTMLButtonElement[]} */ ([...document.querySelectorAll("[data-escenario]")]);
  for (const b of botonesEscenario) {
    b.addEventListener("click", () => {
      controles.establecerModo("manual");
      controles.aplicar(ESCENARIOS[String(b.dataset.escenario)]);
      for (const o of botonesEscenario) o.setAttribute("aria-pressed", String(o === b));
    });
  }

  cargarEnMonitor = (monitor) => {
    mostrarVista("monitor");
    controles.establecerModo("manual");
    controles.aplicar(monitor.sliders);
  };

  cliente.addEventListener("estado", (evento) => {
    const estado = /** @type {CustomEvent} */ (evento).detail;
    hud.setConexion(estado);
    if (estado === "conectado" && modo === "manual") cliente.enviar(controles.condiciones());
  });

  // --- Pipeline único: tanto el modo en vivo como la reproducción pasan por aquí ---
  /** @type {"vivo"|"reproduccion"} */
  let fuente = "vivo";
  let alarmaDetector = false;
  /** @type {any|null} */ let fuegoActual = null;
  /** @type {any|null} */ let frameActual = null;
  let criticoPrevio = false;

  /**
   * @param {any} mensaje {condiciones, evaluacion}
   * @param {{ canalesNorm?: Record<string, number>|null, sinModelo?: boolean }} [extra]
   */
  function aplicarEvaluacion(mensaje, extra = {}) {
    const e = mensaje.evaluacion;
    const c = mensaje.condiciones;
    const nivelModelo = normalizarNivel(e.nivel_riesgo);
    const evento = !extra.sinModelo && hayEvento(c, alarmaDetector);
    // Sin evento el índice es solo potencial latente: no se muestra como ALERTA/CRÍTICO
    const nivel = evento ? nivelModelo : "NOMINAL";
    const indice = Number(e.indice_riesgo) || 0;
    const mostrado = { ...mensaje, evaluacion: { ...e, nivel_riesgo: nivel } };
    cajaNegra.registrar({ t_s: extra.t_s ?? null, evaluacion: { ...e, nivel_riesgo: nivel }, condiciones: c, nivel, evento, alarma: alarmaDetector,
      escenario: extra.escenario, sinModelo: !!extra.sinModelo });
    hud.actualizar(mostrado);
    contexto.actualizar(c);
    const nota = obtener("nota-latente");
    nota.hidden = !(extra.sinModelo || (!evento && nivelModelo !== "NOMINAL"));
    nota.textContent = extra.sinModelo
      ? "FUERA DE DOMINIO: IGNIS no evalúa esta atmósfera; sin índice de riesgo."
      : `Sin evento: potencial latente ${Math.round(indice)} (${TEXTO_NIVEL[nivelModelo]}) si hubiera ignición.`;
    // El número es potencial, no alarma: la etiqueta lo dice en vez de mostrar «NOMINAL» junto a un 76 (confuso)
    if (!nota.hidden && !extra.sinModelo) obtener("lectura-nivel").textContent = "LATENTE";

    pFriaEvaluacion = typeof e.probabilidad_llama_fria === "number" ? e.probabilidad_llama_fria : 0;
    ultimoEstadoEscena = {
      flujoCmS: Number(c?.velocidad_flujo_cm_s) || 0,
      tReaccionK: c?.temperatura_reaccion_k ?? null,
    };
    const velocidad = Number(e.velocidad_propagacion_mm_s) || 0;
    nucleo.establecer({ indice, nivel, velocidad, llamaFria: typeof e.probabilidad_llama_fria === "number" ? e.probabilidad_llama_fria : null });
    gemelo?.establecer({ indice, nivel, velocidad, llamaFria: Math.max(pFriaEvaluacion, pFriaDetector), ...ultimoEstadoEscena });
    audio.actualizar({ indice, nivel });
    audio.sensores(extra.canalesNorm ?? null, evento ? indice / 100 : 0);
    actualizarContraste(c, evento);
    if (!extra.sinModelo) copiloto.notificar(c);
    // Mensajes estructurados (con el factor dominante de la última explicación REST)
    const lista = extra.sinModelo ? [] : construirMensajes({ nivel, evento, evaluacion: e, condiciones: c, fuego: fuegoActual, factores: copiloto.factores() });
    copiloto.fijarMensajes(lista);
    const critico = lista.find((m) => m.tipo === "critico");
    if (critico && !criticoPrevio) { audio.voz(critico.texto); obtener("anuncio").textContent = critico.texto; }
    criticoPrevio = !!critico;
  }

  // Contraste térmico y etiqueta "invisible" (¿Qué ve el astronauta?)
  const etiquetaInvisible = obtener("etiqueta-invisible");
  const botonAstronauta = obtener("boton-astronauta");
  let verComoAstronauta = false;
  /** @param {any} c @param {boolean} evento */
  function actualizarContraste(c, evento) {
    const tr = c?.temperatura_reaccion_k, ta = c?.temperatura_ambiente_k;
    const dt = typeof tr === "number" && typeof ta === "number" ? tr - ta : null;
    const valor = obtener("contraste-valor");
    valor.textContent = dt === null ? "—" : `ΔT ${dt >= 0 ? "+" : ""}${Math.round(dt)} K`;
    obtener("contraste-relleno").style.width = `${dt === null ? 0 : Math.min(100, Math.max(0, (dt / 800) * 100))}%`;
    const invisible = dt !== null && dt >= 50 && tr < UMBRAL_CONTRASTE_VISIBLE_K;
    obtener("contraste-visible").textContent = dt === null ? "—" : invisible ? "Cámara visible: sin contraste" : dt >= 50 ? "Cámara visible: contraste alto" : "Cámara visible: sin evento";
    etiquetaInvisible.hidden = !(verComoAstronauta && invisible && evento);
    etiquetaInvisible.textContent = invisible ? `INVISIBLE EN ESTA MITAD — ${Math.round(tr)} K` : "";
    etiquetaInvisible.style.setProperty("--invisible-x", "var(--foco-x, 50%)");
  }

  cliente.addEventListener("mensaje", (evento) => {
    const mensaje = /** @type {CustomEvent} */ (evento).detail;
    if (fuente !== "vivo") return;
    if (!mensaje?.evaluacion) { hud.actualizar(mensaje); return; }
    aplicarEvaluacion(mensaje, { canalesNorm: ultimosCanalesNorm });
  });
  /** @type {Record<string, number>|null} */ let ultimosCanalesNorm = null;

  // --- Sensores → detector temporal (segundo canal, independiente) ---
  const selectorTraza = /** @type {HTMLSelectElement} */ (obtener("detector-traza"));
  const sensores = new ClienteTiempoReal(obtenerBaseWs());
  const conectarSensores = () => {
    panelDetector.reiniciar();
    pFriaDetector = 0;
    sensores.conectar(`/ws/sensores?tipo=${encodeURIComponent(selectorTraza.value)}&velocidad=1`);
  };
  selectorTraza.addEventListener("change", conectarSensores);
  sensores.addEventListener("estado", (evento) => {
    if (/** @type {CustomEvent} */ (evento).detail === "desconectado") panelDetector.sinSenal();
  });
  sensores.addEventListener("mensaje", (evento) => {
    const m = /** @type {CustomEvent} */ (evento).detail;
    if (m?.tipo !== "sensores" || fuente !== "vivo") return;
    const { pFria, alarmaNueva } = panelDetector.actualizar(m);
    pFriaDetector = pFria;
    alarmaDetector = !!m.alarma_activa;
    ultimosCanalesNorm = Object.fromEntries(Object.values(m.canales ?? {}).map((v, i) => [String(i), Number(v) / ESCALAS_CANALES[i]]));
    if (alarmaNueva) {
      audio.alarma();
      obtener("anuncio").textContent = "Alarma del detector temporal: evento confirmado";
    }
  });

  // --- Reproducción cinemática (guiones evaluados por el backend) ---
  const focoOverlay = obtener("foco-overlay");
  const resultadoWhatIf = obtener("rep-whatif-resultado");
  /** @type {ReturnType<typeof crearReproductor>} */
  const reproductor = crearReproductor({
    alCargar: (guion) => {
      fuegoActual = guion.fuego;
      alarmaDetector = false;
      pFriaDetector = 0;
      panelDetector.reiniciar();
      resultadoWhatIf.textContent = "";
    },
    alEstado: (reproduciendo) => {
      document.body.dataset.reproduciendo = String(reproduciendo);
      if (!reproduciendo) audio.sensores(null, 0);
    },
    alFrame: (frame, guion) => {
      frameActual = frame;
      alarmaDetector = !!frame.alarma_detector;
      const sinModelo = frame.indice_riesgo === null || frame.indice_riesgo === undefined;
      const pEvento = frame.p_evento ?? 0;
      const fria = frame.clase_detector === "LLAMA_FRIA";
      const probs = { NOMINAL: 1 - pEvento, LLAMA_FRIA: fria ? pEvento : 0, LLAMA_CALIENTE: fria ? 0 : pEvento };
      const prev = panelDetector.actualizar({ probabilidades: probs, alarma_activa: frame.alarma_detector, alarma_nueva: false,
        canales: frame.canales, latencia_ms: guion.latencias_ms?.tcn_ms_medio ?? 0 });
      pFriaDetector = prev.pFria;
      const evaluacion = sinModelo
        ? { indice_riesgo: 0, nivel_riesgo: "NOMINAL", probabilidad_propagacion: 0, velocidad_propagacion_mm_s: 0, incertidumbre_mm_s: 0,
            probabilidad_llama_fria: null, estado_llama_fria: "NO_EVALUADA", acciones_sugeridas: [], origen_datos: "sintetico" }
        : { indice_riesgo: frame.indice_riesgo, nivel_riesgo: frame.nivel_riesgo, probabilidad_propagacion: frame.probabilidad_propagacion,
            velocidad_propagacion_mm_s: frame.velocidad_propagacion_mm_s, incertidumbre_mm_s: frame.incertidumbre_mm_s ?? 0,
            probabilidad_llama_fria: frame.probabilidad_llama_fria, estado_llama_fria: frame.estado_llama_fria ?? "NO_EVALUADA",
            acciones_sugeridas: frame.acciones_sugeridas ?? [], origen_datos: frame.origen_datos ?? "sintetico",
            fuera_de_dominio: frame.fuera_de_dominio };
      const condiciones = { ...frame.condiciones };
      aplicarEvaluacion({ tipo: "evaluacion", condiciones, evaluacion },
        { canalesNorm: frame.canales_norm ? Object.fromEntries(Object.entries(frame.canales_norm)) : null, sinModelo,
          t_s: frame.t_s, escenario: guion.nombre });
      if (frame.alarma_detector && !criticoPrevioDetector) audio.alarma();
      criticoPrevioDetector = !!frame.alarma_detector;
      focoOverlay.hidden = !(guion.fuego && frame.evento_activo);
      if (guion.fuego) obtener("foco-texto").textContent = `FOCO ${guion.fuego.sector} [${guion.fuego.x_m.toFixed(1)}, ${guion.fuego.y_m.toFixed(1)}] · simulado`;
    },
    alWhatIf: async (condiciones) => {
      if (!condiciones || !frameActual) { resultadoWhatIf.textContent = ""; return; }
      const inicio = performance.now();
      try {
        const body = Object.fromEntries(Object.entries(condiciones).filter(([, v]) => v !== null));
        const r = await fetch("/api/v1/predict", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (!r.ok) { resultadoWhatIf.textContent = r.status === 422 ? "Valores fuera del dominio operativo del modelo." : `Error ${r.status}`; return; }
        const w = await r.json();
        reproductor.registrarRtt(performance.now() - inicio);
        const base = frameActual.indice_riesgo;
        const d = w.indice_riesgo - base;
        const nivelW = hayEvento(condiciones, alarmaDetector) ? TEXTO_NIVEL[normalizarNivel(w.nivel_riesgo)] : "sin evento (latente)";
        resultadoWhatIf.textContent = `Actual ${base.toFixed(0)} → con cambios ${w.indice_riesgo.toFixed(0)} (${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(0)}) · ${nivelW} · llama ${w.velocidad_propagacion_mm_s.toFixed(1)} mm/s`;
      } catch { resultadoWhatIf.textContent = "No se pudo consultar el modelo."; }
    },
  });
  let criticoPrevioDetector = false;

  // Foco 3D: la marca HTML sigue a la llama en cada fotograma
  gemelo?.alFotograma(({ x, y, visible }) => {
    focoOverlay.style.left = `${x * 100}%`;
    focoOverlay.style.top = `${y * 100}%`;
    focoOverlay.style.visibility = visible ? "visible" : "hidden";
    etiquetaInvisible.style.left = `${x * 100}%`;
    etiquetaInvisible.style.top = `${y * 100}%`;
  });

  // Fuente: en vivo (WebSocket) o reproducción (guion)
  const botonesFuente = /** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-fuente]"));
  /** @param {"vivo"|"reproduccion"} nueva */
  function fijarFuente(nueva) {
    fuente = nueva;
    document.body.dataset.fuente = nueva;
    for (const b of botonesFuente) b.setAttribute("aria-pressed", String(b.dataset.fuente === nueva));
    obtener("reproductor").hidden = nueva !== "reproduccion";
    obtener("panel-modo-vivo").hidden = nueva !== "vivo";
    alarmaDetector = false; pFriaDetector = 0; criticoPrevio = false; fuegoActual = null;
    focoOverlay.hidden = true;
    copiloto.fijarMensajes([]);
    panelDetector.reiniciar();
    if (nueva === "reproduccion") {
      cliente.cerrar(); sensores.cerrar();
      reproductor.activar();
    } else {
      reproductor.pausar();
      cliente.conectar(modo === "manual" ? RUTA_MANUAL : RUTA_ESCENARIO);
      conectarSensores();
    }
  }
  for (const b of botonesFuente) b.addEventListener("click", () => fijarFuente(/** @type {any} */ (b.dataset.fuente)));

  // "¿Qué ve el astronauta?": oculta la mitad IR unos segundos y muestra qué queda visible
  /** @type {ReturnType<typeof setTimeout>|undefined} */ let temporizadorAstronauta;
  /** @type {"visible"|"ir"|"dividido"} */ let visionPrevia = "visible";
  botonAstronauta.addEventListener("click", () => {
    const botonesVision = /** @type {NodeListOf<HTMLButtonElement>} */ (document.querySelectorAll("[data-vision]"));
    if (!verComoAstronauta) {
      visionPrevia = /** @type {any} */ (document.body.dataset.vision ?? "visible");
      verComoAstronauta = true;
      botonAstronauta.setAttribute("aria-pressed", "true");
      botonAstronauta.textContent = "Volver a IR";
      [...botonesVision].find((b) => b.dataset.vision === "visible")?.click();
      temporizadorAstronauta = setTimeout(() => botonAstronauta.click(), 8000);
    } else {
      verComoAstronauta = false;
      clearTimeout(temporizadorAstronauta);
      botonAstronauta.setAttribute("aria-pressed", "false");
      botonAstronauta.textContent = "¿Qué ve el astronauta?";
      [...botonesVision].find((b) => b.dataset.vision === visionPrevia)?.click();
      etiquetaInvisible.hidden = true;
    }
  });

  iniciarValidacion();

  // Reloj de sesión T+ mm:ss
  const reloj = obtener("reloj");
  const inicio = Date.now();
  setInterval(() => {
    const total = Math.floor((Date.now() - inicio) / 1000);
    reloj.textContent = `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  }, 1000);

  // Chip de motores disponibles
  const chipMotores = obtener("chip-motores");
  const refrescarMotores = async () => {
    try {
      const r = await fetch("/api/v1/modelo/estado");
      if (!r.ok) return;
      const e = await r.json();
      const dl = e.componentes?.profundo?.estado;
      const det = e.componentes?.detector?.estado;
      chipMotores.textContent = `Motores: ${(e.motores ?? []).join(" + ") || "—"}${det === "listo" ? " · detector" : ""}`;
      chipMotores.dataset.origen = dl === "listo" && det === "listo" ? "real" : "sintetico";
      // El detector puede cargarse después del arranque: si no hay señal, reconectar
      if (det === "listo" && sensores.estaCerrado) conectarSensores();
    } catch { /* sin servidor: se reintenta */ }
  };
  refrescarMotores();
  setInterval(refrescarMotores, 6000);

  nucleo.iniciar();
  controles.establecerModo("escenario");
  conectarSensores();
}

iniciar();
