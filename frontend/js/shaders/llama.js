// @ts-check
/** GLSL de la llama visible y de la capa de llama fría (solo visible en visión IR). */

/** Cabecera común: decide si el fragmento se pinta en modo IR (modo 2 = dividido). */
export const GLSL_MODO = /* glsl */ `
uniform float uModo;      // 0 visible · 1 infrarrojo · 2 dividido
uniform float uDivision;  // fracción de pantalla (0..1) que muestra IR en modo dividido
uniform vec2 uResolucion; // tamaño del buffer de dibujo en píxeles
bool esIR() {
  if (uModo > 1.5) return gl_FragCoord.x < uDivision * uResolucion.x;
  return uModo > 0.5;
}
`;

const RUIDO = /* glsl */ `
float hash(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float ruido(vec3 x) {
  vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) { return 0.5 * ruido(p) + 0.25 * ruido(p * 2.03) + 0.125 * ruido(p * 4.01); }
`;

export const VERTICE_VOLUMEN = /* glsl */ `
varying vec3 vNormal; varying vec3 vPos; varying vec3 vVista;
void main() {
  vPos = position;
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vVista = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`;

/** Llama de difusión en microgravedad: casi esférica, con núcleo azul y borde ámbar. */
export const FRAGMENTO_LLAMA = /* glsl */ `
${GLSL_MODO}
${RUIDO}
uniform float uTiempo; uniform float uIntensidad;
varying vec3 vNormal; varying vec3 vPos; varying vec3 vVista;
void main() {
  float borde = pow(1.0 - abs(dot(vNormal, vVista)), 1.6);
  float n = fbm(vPos * 3.2 + vec3(0.0, uTiempo * 0.9, uTiempo * 0.5));
  float cuerpo = clamp(0.55 + 0.9 * n - borde * 0.55, 0.0, 1.0) * uIntensidad;
  vec3 color;
  if (esIR()) {
    // Falso color térmico: negro → violeta → naranja → blanco
    float t = clamp(cuerpo * 1.4, 0.0, 1.0);
    color = mix(vec3(0.1, 0.0, 0.25), vec3(1.0, 0.45, 0.05), smoothstep(0.0, 0.6, t));
    color = mix(color, vec3(1.0, 0.97, 0.85), smoothstep(0.6, 1.0, t));
  } else {
    color = mix(vec3(0.15, 0.35, 1.0), vec3(1.0, 0.62, 0.15), smoothstep(0.1, 0.8, n + borde * 0.4));
    color = mix(color, vec3(1.0, 0.92, 0.7), smoothstep(0.7, 1.0, cuerpo));
  }
  gl_FragColor = vec4(color * (0.3 + 0.45 * cuerpo), cuerpo * 0.5);
}
`;

/**
 * Llama fría: NO emite luz visible. Solo se dibuja en el lado IR (o con visión IR),
 * por eso a ojo y en cámaras visibles "no hay nada" aunque haya reacción.
 */
export const FRAGMENTO_CAPA_FRIA = /* glsl */ `
${GLSL_MODO}
${RUIDO}
uniform float uTiempo; uniform float uProbabilidad;
varying vec3 vNormal; varying vec3 vPos; varying vec3 vVista;
void main() {
  if (!esIR()) discard;
  float fresnel = pow(1.0 - abs(dot(vNormal, vVista)), 2.0);
  float n = fbm(vPos * 2.4 + vec3(uTiempo * 0.35, 0.0, uTiempo * 0.2));
  float ondas = 0.5 + 0.5 * sin(vPos.x * 14.0 - uTiempo * 2.2 + n * 6.0);
  float a = (0.18 + 0.55 * fresnel) * (0.4 + 0.6 * n) * (0.65 + 0.35 * ondas) * uProbabilidad;
  vec3 color = mix(vec3(0.35, 0.1, 0.9), vec3(0.3, 0.85, 1.0), fresnel + 0.3 * n);
  gl_FragColor = vec4(color, a);
}
`;

/** Combustible: opaco en visible; en IR se tiñe según su temperatura normalizada. */
export const FRAGMENTO_COMBUSTIBLE = /* glsl */ `
${GLSL_MODO}
uniform float uCalor; // 0..1
varying vec3 vNormal; varying vec3 vPos; varying vec3 vVista;
void main() {
  float luz = 0.35 + 0.65 * max(dot(vNormal, normalize(vec3(0.4, 0.8, 0.5))), 0.0);
  vec3 color = vec3(0.16, 0.14, 0.12) * luz;
  if (esIR()) {
    float t = clamp(uCalor + 0.08 * luz, 0.0, 1.0);
    color = mix(vec3(0.02, 0.0, 0.12), vec3(0.9, 0.3, 0.02), smoothstep(0.0, 0.7, t));
    color = mix(color, vec3(1.0, 0.95, 0.8), smoothstep(0.7, 1.0, t));
  } else {
    color += vec3(0.5, 0.15, 0.02) * smoothstep(0.55, 1.0, uCalor);
  }
  gl_FragColor = vec4(color, 1.0);
}
`;

export const VERTICE_LINEA = /* glsl */ `void main() { gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
export const FRAGMENTO_LINEA = /* glsl */ `
${GLSL_MODO}
uniform vec3 uColorVisible; uniform vec3 uColorIR; uniform float uAlfa;
void main() { gl_FragColor = vec4(esIR() ? uColorIR : uColorVisible, uAlfa); }
`;

export const VERTICE_FLUJO = /* glsl */ `
uniform float uTiempo; uniform float uVelocidad; uniform float uLargo;
attribute float aFase; attribute float aOffset;
varying float vAlfa;
void main() {
  vec3 p = position;
  float x = mod(p.x + uTiempo * uVelocidad + aFase * uLargo, uLargo) - 0.5 * uLargo;
  p.x = x;
  p.y += 0.02 * sin(uTiempo * 0.7 + aOffset * 6.28);
  vAlfa = smoothstep(0.5 * uLargo, 0.35 * uLargo, abs(x));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = 2.2 * (3.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}
`;
export const FRAGMENTO_FLUJO = /* glsl */ `
${GLSL_MODO}
varying float vAlfa;
void main() {
  vec2 d = gl_PointCoord - 0.5; float r = length(d); if (r > 0.5) discard;
  vec3 c = esIR() ? vec3(0.45, 0.4, 1.0) : vec3(0.31, 0.82, 1.0);
  gl_FragColor = vec4(c, vAlfa * (1.0 - r * 2.0) * 0.55);
}
`;
