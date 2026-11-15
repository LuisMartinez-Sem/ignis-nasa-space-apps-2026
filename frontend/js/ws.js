// @ts-check
/**
 * Cliente WebSocket con reconexión exponencial.
 * Eventos (CustomEvent): "estado" → detail: "conectando"|"conectado"|"desconectado";
 *                        "mensaje" → detail: objeto JSON del servidor.
 */

// Solo host[:puerto]: evita que ?api= inyecte rutas, credenciales o esquemas
const PATRON_HOST = /^[A-Za-z0-9.-]+(?::\d{1,5})?$/;
const RETARDO_MIN_MS = 500;
const RETARDO_MAX_MS = 8000;

/**
 * Base ws(s):// del backend. Permite `?api=localhost:8000` si el HUD se sirve aparte.
 * @returns {string}
 */
export function obtenerBaseWs() {
  const protocolo = window.location.protocol === "https:" ? "wss:" : "ws:";
  const api = new URLSearchParams(window.location.search).get("api");
  if (api && PATRON_HOST.test(api)) return `${protocolo}//${api}`;
  if (window.location.host) return `${protocolo}//${window.location.host}`;
  return "ws://localhost:8000";
}

export class ClienteTiempoReal extends EventTarget {
  #base;
  /** @type {string|null} */ #ruta = null;
  /** @type {WebSocket|null} */ #socket = null;
  #intentos = 0;
  /** @type {number|undefined} */ #temporizador;
  #cerradoManual = false;

  /** @param {string} base Ej.: "ws://localhost:8000". */
  constructor(base) {
    super();
    this.#base = base;
  }

  /**
   * Abre (o reabre) la conexión a `ruta`, cerrando la anterior.
   * @param {string} ruta Ej.: "/ws/demo?ritmo_hz=2".
   */
  conectar(ruta) {
    this.cerrar();
    this.#ruta = ruta;
    this.#cerradoManual = false;
    this.#intentos = 0;
    this.#abrir();
  }

  /**
   * Envía un objeto como JSON si el canal está abierto.
   * @param {object} carga
   * @returns {boolean} true si se envió.
   */
  enviar(carga) {
    if (this.#socket?.readyState !== WebSocket.OPEN) return false;
    this.#socket.send(JSON.stringify(carga));
    return true;
  }

  /** True si no hay socket abierto (p. ej. el servidor rechazó por detector no listo). */
  get estaCerrado() {
    return this.#socket === null || this.#socket.readyState === WebSocket.CLOSED;
  }

  /** Cierra sin reintentar. */
  cerrar() {
    this.#cerradoManual = true;
    clearTimeout(this.#temporizador);
    const socket = this.#socket;
    this.#socket = null; // los eventos del socket viejo se ignoran por identidad
    socket?.close();
  }

  /** @param {string} tipo @param {unknown} detalle */
  #emitir(tipo, detalle) {
    this.dispatchEvent(new CustomEvent(tipo, { detail: detalle }));
  }

  #abrir() {
    this.#emitir("estado", "conectando");
    const socket = new WebSocket(this.#base + this.#ruta);
    this.#socket = socket;

    socket.addEventListener("open", () => {
      if (socket !== this.#socket) return;
      this.#intentos = 0;
      this.#emitir("estado", "conectado");
    });
    socket.addEventListener("message", (evento) => {
      if (socket !== this.#socket) return;
      try {
        this.#emitir("mensaje", JSON.parse(evento.data));
      } catch (error) {
        console.error("[IGNIS] Mensaje WebSocket no es JSON válido", error);
      }
    });
    socket.addEventListener("close", () => {
      if (socket !== this.#socket) return;
      this.#emitir("estado", "desconectado");
      if (!this.#cerradoManual) this.#reintentar();
    });
  }

  #reintentar() {
    const retardo = Math.min(RETARDO_MAX_MS, RETARDO_MIN_MS * 2 ** this.#intentos);
    this.#intentos += 1;
    this.#temporizador = setTimeout(() => this.#abrir(), retardo);
  }
}
