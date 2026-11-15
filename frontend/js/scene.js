// @ts-check
/**
 * Gemelo digital 3D del módulo (Three.js vendorizado).
 *
 * Qué muestra, en una mirada:
 *  - Anillos de riesgo pulsantes alrededor de la muestra (firma visual de IGNIS): la
 *    frecuencia del pulso y el color dicen el nivel sin leer ningún número.
 *  - Llama visible (ámbar/azul) cuyo tamaño sigue al índice y la velocidad.
 *  - Capa de LLAMA FRÍA: solo existe en la visión infrarroja. En modo "dividido" una
 *    mitad de la pantalla es la cámara normal y la otra la cámara IR: se ve que a ojo
 *    "no pasa nada" mientras IGNIS ya detecta la reacción.
 *  - Flujo de aire (partículas) con la velocidad real del módulo.
 */
import * as THREE from "../vendor/three.bundle.js";
import { EffectComposer, OrbitControls, OutputPass, RenderPass, UnrealBloomPass } from "../vendor/three.bundle.js";
import { COLOR_NIVEL } from "./paleta.js";
import {
  FRAGMENTO_CAPA_FRIA, FRAGMENTO_COMBUSTIBLE, FRAGMENTO_FLUJO, FRAGMENTO_LLAMA, FRAGMENTO_LINEA,
  VERTICE_FLUJO, VERTICE_LINEA, VERTICE_VOLUMEN,
} from "./shaders/llama.js";

const LARGO_MODULO = 4;
const N_PARTICULAS = 420;
const MODOS = { visible: 0, ir: 1, dividido: 2 };

/**
 * @typedef {{ indice: number, nivel: import("./paleta.js").NivelRiesgo, velocidad: number,
 *   llamaFria: number|null, flujoCmS: number, tReaccionK: number|null }} EstadoEscena
 */

/** @param {number} x @param {number} a @param {number} b */
const suavizar = (x, a, b) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** @returns {boolean} */
export function webglDisponible() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * @param {HTMLCanvasElement} lienzo
 * @param {{ reducirMovimiento: boolean }} opciones
 */
export function crearEscena(lienzo, { reducirMovimiento }) {
  const renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, alpha: false, powerPreference: "high-performance" });
  const escena = new THREE.Scene();
  // Fondo por escena (gestión de color correcta dentro del EffectComposer; setClearColor lo aclaraba)
  escena.background = new THREE.Color(0x070a12);
  escena.fog = new THREE.FogExp2(0x0a0e17, 0.11);
  const camara = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
  camara.position.set(2.6, 1.35, 4.9);
  const controles = new OrbitControls(camara, lienzo);
  controles.enableDamping = true;
  controles.minDistance = 1.6;
  controles.maxDistance = 8;
  controles.maxPolarAngle = Math.PI * 0.62;
  controles.autoRotate = !reducirMovimiento;
  controles.autoRotateSpeed = 0.35;
  controles.target.set(0, 0, 0);
  // Cualquier interacción detiene la rotación automática (no pelear con el usuario)
  controles.addEventListener("start", () => (controles.autoRotate = false));

  // --- Uniformes compartidos ---
  const comunes = {
    uModo: { value: 0 }, uDivision: { value: 0.5 }, uResolucion: { value: new THREE.Vector2(1, 1) },
    uTiempo: { value: 0 },
  };

  // --- Módulo: costillas y largueros en alambre (estética de HUD) ---
  const puntosLinea = [];
  const RADIO = 1.25;
  for (let i = 0; i <= 13; i++) {
    const x = -LARGO_MODULO / 2 + (i * LARGO_MODULO) / 13;
    for (let s = 0; s < 48; s++) {
      const a0 = (s / 48) * Math.PI * 2, a1 = ((s + 1) / 48) * Math.PI * 2;
      puntosLinea.push(x, Math.cos(a0) * RADIO, Math.sin(a0) * RADIO, x, Math.cos(a1) * RADIO, Math.sin(a1) * RADIO);
    }
  }
  for (let l = 0; l < 16; l++) {
    const a = (l / 16) * Math.PI * 2;
    puntosLinea.push(-LARGO_MODULO / 2, Math.cos(a) * RADIO, Math.sin(a) * RADIO, LARGO_MODULO / 2, Math.cos(a) * RADIO, Math.sin(a) * RADIO);
  }
  const geoLineas = new THREE.BufferGeometry();
  geoLineas.setAttribute("position", new THREE.Float32BufferAttribute(puntosLinea, 3));
  const matLineas = new THREE.ShaderMaterial({
    uniforms: { ...comunes, uColorVisible: { value: new THREE.Color(0x1d4a63) }, uColorIR: { value: new THREE.Color(0x2a1a55) }, uAlfa: { value: 0.55 } },
    vertexShader: VERTICE_LINEA, fragmentShader: FRAGMENTO_LINEA, transparent: true, depthWrite: false,
  });
  escena.add(new THREE.LineSegments(geoLineas, matLineas));

  // --- Combustible (tira de 0.9 × 0.28) en el eje del módulo ---
  const matCombustible = new THREE.ShaderMaterial({
    uniforms: { ...comunes, uCalor: { value: 0 } },
    vertexShader: VERTICE_VOLUMEN, fragmentShader: FRAGMENTO_COMBUSTIBLE,
  });
  const combustible = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.025, 0.34), matCombustible);
  escena.add(combustible);

  // --- Llama visible ---
  const matLlama = new THREE.ShaderMaterial({
    uniforms: { ...comunes, uIntensidad: { value: 0 } },
    vertexShader: VERTICE_VOLUMEN, fragmentShader: FRAGMENTO_LLAMA,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const llama = new THREE.Mesh(new THREE.SphereGeometry(0.5, 40, 28), matLlama);
  llama.position.set(0.05, 0.16, 0);
  llama.visible = false;
  escena.add(llama);

  // --- Capa de llama fría ---
  const matFria = new THREE.ShaderMaterial({
    uniforms: { ...comunes, uProbabilidad: { value: 0 } },
    vertexShader: VERTICE_VOLUMEN, fragmentShader: FRAGMENTO_CAPA_FRIA,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
  const capaFria = new THREE.Mesh(new THREE.SphereGeometry(0.5, 48, 32), matFria);
  capaFria.position.set(0.05, 0.2, 0);
  escena.add(capaFria);

  // --- Flujo de aire ---
  const geoFlujo = new THREE.BufferGeometry();
  const pos = new Float32Array(N_PARTICULAS * 3), fase = new Float32Array(N_PARTICULAS), desfase = new Float32Array(N_PARTICULAS);
  for (let i = 0; i < N_PARTICULAS; i++) {
    const r = Math.sqrt(Math.random()) * (RADIO - 0.1), a = Math.random() * Math.PI * 2;
    pos.set([0, Math.cos(a) * r, Math.sin(a) * r], i * 3);
    fase[i] = Math.random(); desfase[i] = Math.random();
  }
  geoFlujo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geoFlujo.setAttribute("aFase", new THREE.BufferAttribute(fase, 1));
  geoFlujo.setAttribute("aOffset", new THREE.BufferAttribute(desfase, 1));
  const matFlujo = new THREE.ShaderMaterial({
    uniforms: { ...comunes, uVelocidad: { value: 0.1 }, uLargo: { value: LARGO_MODULO } },
    vertexShader: VERTICE_FLUJO, fragmentShader: FRAGMENTO_FLUJO,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  escena.add(new THREE.Points(geoFlujo, matFlujo));

  // --- Anillos de riesgo (billboards): 3 concéntricos + halo ---
  const grupoAnillos = new THREE.Group();
  grupoAnillos.position.set(0.05, 0.1, 0);
  /** @type {{ malla: THREE.Mesh, base: number }[]} */
  const anillos = [];
  [0.42, 0.6, 0.78].forEach((radio, i) => {
    const mat = new THREE.MeshBasicMaterial({ color: 0x4fd1ff, transparent: true, opacity: 0.5, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending });
    const malla = new THREE.Mesh(new THREE.RingGeometry(radio - 0.012 - i * 0.004, radio + 0.012 + i * 0.004, 128), mat);
    grupoAnillos.add(malla);
    anillos.push({ malla, base: radio });
  });
  escena.add(grupoAnillos);

  // --- Postproceso: bloom ---
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(escena, camara));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.4, 0.5, 0.78);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // --- Estado dinámico (con inercia para que nada "salte") ---
  /** @type {EstadoEscena} */
  let objetivo = { indice: 0, nivel: "NOMINAL", velocidad: 0, llamaFria: null, flujoCmS: 10, tReaccionK: null };
  const suave = { indice: 0, velocidad: 0, fria: 0, flujo: 10, calor: 0 };
  const colorNivel = new THREE.Color(0x4fd1ff);
  const colorObjetivo = new THREE.Color(0x4fd1ff);
  let fasePulso = 0;

  function redimensionar() {
    const caja = lienzo.parentElement?.getBoundingClientRect() ?? lienzo.getBoundingClientRect();
    const ancho = Math.max(1, Math.floor(caja.width)), alto = Math.max(1, Math.floor(caja.height));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(ancho, alto, false);
    composer.setPixelRatio(dpr);
    composer.setSize(ancho, alto);
    bloom.resolution.set(ancho, alto);
    camara.aspect = ancho / alto;
    camara.updateProjectionMatrix();
    comunes.uResolucion.value.set(ancho * dpr, alto * dpr);
  }
  const observador = new ResizeObserver(redimensionar);
  observador.observe(lienzo.parentElement ?? lienzo);
  redimensionar();

  let visible = true;
  const io = new IntersectionObserver(([entrada]) => (visible = entrada.isIntersecting));
  io.observe(lienzo);
  let enSegundoPlano = document.hidden;
  const alCambiarVisibilidad = () => (enSegundoPlano = document.hidden);
  document.addEventListener("visibilitychange", alCambiarVisibilidad);

  const reloj = new THREE.Timer();
  let marco = 0;
  let activo = true;

  /** @type {((p: { x: number, y: number, visible: boolean }) => void)|null} */ let alFotograma = null;
  const puntoFoco = new THREE.Vector3();
  function bucle() {
    if (!activo) return;
    marco = requestAnimationFrame(bucle);
    if (!visible || enSegundoPlano) return;
    reloj.update();
    const dt = Math.min(reloj.getDelta(), 0.1);
    const t = (comunes.uTiempo.value += reducirMovimiento ? 0 : dt);
    const k = 1 - Math.exp(-dt * 4); // inercia exponencial independiente del fps
    suave.indice += (objetivo.indice - suave.indice) * k;
    suave.velocidad += (objetivo.velocidad - suave.velocidad) * k;
    suave.fria += ((objetivo.llamaFria ?? 0) - suave.fria) * k;
    suave.flujo += (objetivo.flujoCmS - suave.flujo) * k;
    const calorObjetivo = objetivo.tReaccionK == null ? suave.indice / 160 : suavizar(objetivo.tReaccionK, 295, 1200);
    suave.calor += (calorObjetivo - suave.calor) * k;

    // Llama visible: aparece sobre ~35 de índice y crece con la velocidad
    const presencia = suavizar(suave.indice, 30, 85);
    llama.visible = presencia > 0.02;
    const radioLlama = 0.07 + 0.2 * presencia * (0.6 + Math.min(suave.velocidad / 10, 1) * 0.6);
    llama.scale.setScalar(radioLlama * 2);
    llama.scale.x *= 1.25; // algo alargada en el sentido del flujo
    matLlama.uniforms.uIntensidad.value = presencia;

    // Llama fría: alcance fijo, opacidad por probabilidad (invisible fuera de IR)
    matFria.uniforms.uProbabilidad.value = suave.fria;
    capaFria.scale.set(1.2 + 0.3 * suave.fria, 0.8, 0.8);
    matCombustible.uniforms.uCalor.value = Math.min(1, suave.calor);
    matFlujo.uniforms.uVelocidad.value = 0.05 + (suave.flujo / 60) * 0.9;

    // Anillos: color por nivel; pulso 0,7 → 3 Hz con el índice
    colorObjetivo.setRGB(...COLOR_NIVEL[objetivo.nivel].map((c) => c / 255));
    colorNivel.lerp(colorObjetivo, k);
    const frecuencia = 0.7 + (suave.indice / 100) * 2.3;
    fasePulso += reducirMovimiento ? 0 : dt * frecuencia * Math.PI * 2;
    anillos.forEach((a, i) => {
      const onda = Math.sin(fasePulso - i * 0.9);
      const amplitud = 0.03 + (suave.indice / 100) * 0.07;
      a.malla.scale.setScalar(1 + onda * amplitud);
      const mat = /** @type {THREE.MeshBasicMaterial} */ (a.malla.material);
      mat.color.copy(colorNivel);
      mat.opacity = (0.22 + 0.5 * (suave.indice / 100)) * (0.65 + 0.35 * (onda * 0.5 + 0.5)) * (1 - i * 0.2);
    });
    grupoAnillos.quaternion.copy(camara.quaternion);
    bloom.strength = 0.3 + 0.35 * presencia + (comunes.uModo.value > 0.5 ? 0.15 : 0);

    controles.update();
    if (alFotograma) {
      puntoFoco.copy(llama.position).project(camara);
      alFotograma({ x: puntoFoco.x * 0.5 + 0.5, y: -puntoFoco.y * 0.5 + 0.5, visible: puntoFoco.z < 1 });
    }
    composer.render();
  }
  bucle();

  return {
    /** @param {Partial<EstadoEscena>} estado */
    establecer(estado) {
      objetivo = { ...objetivo, ...estado };
    },
    /** @param {"visible"|"ir"|"dividido"} modo */
    fijarVision(modo) {
      comunes.uModo.value = MODOS[modo];
    },
    /** @param {number} fraccion Posición del divisor (0..1) en el modo dividido. */
    fijarDivision(fraccion) {
      comunes.uDivision.value = Math.min(0.95, Math.max(0.05, fraccion));
    },
    /** Posición de pantalla (0..1) del foco en cada fotograma, para superponer marcas HTML. @param {((p: { x: number, y: number, visible: boolean }) => void)|null} fn */
    alFotograma(fn) {
      alFotograma = fn;
    },
    /** Vuelve a la vista inicial. */
    reiniciarCamara() {
      camara.position.set(2.6, 1.35, 4.9);
      controles.target.set(0, 0, 0);
    },
    /** Libera GPU y listeners. */
    destruir() {
      activo = false;
      cancelAnimationFrame(marco);
      observador.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", alCambiarVisibilidad);
      controles.dispose();
      composer.dispose();
      renderer.dispose();
    },
  };
}
