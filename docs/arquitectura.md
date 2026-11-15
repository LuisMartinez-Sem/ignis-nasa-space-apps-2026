# Arquitectura de IGNIS

```
data/{raw,processed,incidents,versiones}      src/                         api/                    frontend/
 CSV PSI ─► pipeline_datos (mapeo de unidades,  domain · config              main (lifespan)         index.html (Monitor | Incidentes)
           perfil, versionado SHA-256)          dataset_sintetico            middleware (CSP, id)    js/scene.js   gemelo Three.js
 incidents/*.json ─► incidentes_historicos      model (RF) · modelo_profundo routes/predict          js/anillos.js núcleo 2D (firma)
                                                senales · detector_temporal  routes/incidentes       js/detector.js js/copilot.js
                                                predictor (multi-motor)      routes/modelo · datos   js/incidents.js js/audio.js
                                                servicio_modelos             websocket (/ws/*)       vendor/three.bundle.js (offline)
                                                simulador_incidentes
```

## Flujo de arranque
`ServicioModelos.iniciar()` carga el RF (bloqueante, segundos) y lanza **en segundo plano** el motor profundo y el
detector (pesos `modelos/*.pt`; si faltan y `ENTRENAR_PROFUNDO_AL_INICIAR=true`, se entrenan). La API responde en cuanto
el RF está listo; `/api/v1/modelo/estado` informa del resto y el HUD lo muestra.

## Modelos
- **RF**: línea base robusta con pocos datos.
- **Ensemble profundo** (5 redes en lote, NLL gaussiana heterocedástica + BCE): incertidumbre aleatoria + epistémica y
  `afinar()` para transfer learning con datos reales (tasa baja + replay del sintético).
- **Detector temporal**: TCN causal dilatada (campo receptivo 63 muestras, 6 canales, 10 Hz). Alarma = 3 votos
  consecutivos con P(evento) ≥ 0,60; se rearma tras 10 votos en calma. Una muestra cuesta ≈1 ms (CPU).
- **Fuera de dominio**: la envolvente de entrenamiento marca extrapolación en cada respuesta.
- **Explicabilidad**: sensibilidad local (+10 % por variable), no causal.

## Contratos clave
| Ruta | Uso |
|---|---|
| `POST /api/v1/predict?motor=rf\|profundo&explicar=true` | Evaluación (409 si el motor aún no está listo) |
| `POST /api/v1/explain` | Factores que mueven el riesgo |
| `GET /api/v1/modelo/estado` · `/reporte` | Estado de componentes · métricas, calibración y latencia |
| `GET /api/v1/datos/versiones[/{id}]` | Versiones del dataset y huecos de cobertura |
| `GET /api/v1/incidentes[/{id}[/simular]]` | Ver `docs/incidentes.md` |
| `WS /ws/sensores?tipo=…&velocidad=…` | Traza de 6 canales → detector, muestra a muestra |
| `WS /ws/predict` · `/ws/demo` | Evaluación bajo demanda · escenario cíclico |

## Seguridad y accesibilidad
CSP `'self'` (Three.js y fuentes vendorizados), cabeceras `nosniff`/`X-Frame-Options`, CORS explícito sin credenciales,
tope de conexiones WS, ids validados por regex (anti path-traversal), pesos cargados con `weights_only=True`,
texto del servidor siempre vía `textContent`. HUD: roles ARIA (tabs, meter, status), nivel de riesgo con forma además
de color, foco visible, `prefers-reduced-motion`, audio apagado por defecto.

## Cómo llegan los datos reales
`python -m src.pipeline_datos ingestar --csv … --mapeo …` → nueva versión → `python -m src.entrenamiento --version ID`.
El reporte compara RF vs. profundo sobre la misma partición agrupada por experimento.

## Super Intelligence: resumir, clasificar, interpretar
`GET /api/v1/si-insights` (`src/insights.py`) responde al requisito de la NASA de que el sistema «resuma, clasifique e interprete» los datos:
- **Resume**: condensa las anclas (`data/anclas_reales.json`) en frases cortas; las cifras se leen del archivo, no se escriben a mano.
- **Clasifica**: cada insight lleva un `tipo` (Riesgo, Alerta, Clasificación, Interpretación, Límite).
- **Interpreta**: explica qué significa cada cifra para el índice de riesgo (pesos 55/30/15, normalización 4,74 mm/s).
- **Honestidad**: cada insight declara `fuente` y `verificacion`. Son textos predefinidos, no generados en vivo, y las fuentes de Saffire-I y FLEX no fueron verificadas por IGNIS. Cubre el requisito de forma parcial: no hay análisis automático de datos nuevos.
(El archivo se llama `arquitectura.md`, no `architecture.md`.)

## SI Dashboard (reto NASA 2026) — vista principal
La pestaña **Investigaciones** es ahora la vista principal; el Monitor (detector, copiloto, gemelo 3D) pasó a una pestaña aparte.
- `data/investigaciones.json`: 19 investigaciones (BASS, BASS-II, SPICE, SLICE, Saffire-I/II/III, SAME, SAME-R, DAFT, DAFT-2, FLEX, FLEX-2, CFI, ACME CFI-G/BRE/E-FIELD, LUCI, FM2). Salen del texto del reto y de las anclas del equipo; **los metadatos reales de PSI no se han leído** (O₂, flujo y presión desconocidos = `null`, nunca inventados).
- `GET /api/v1/investigaciones` (catálogo + relevancia 0-100 por ISS/Luna/Marte/traje), `/ranking?entorno=&area=&combustible=` (desglose e interpretación por investigación), `/comparar?ids=`, `/gaps` (huecos de la NASA y de IGNIS), `/export?formato=csv|json&conjunto=investigaciones|anclas`, `/aplicaciones-terrestres`, `/{id}`.
- `POST /api/v1/preset/lunar`: evalúa O₂ ≥ 30 % y P ≤ 70,3 kPa frente a la ISS (incluye pO₂); advierte que la gravedad lunar es una extrapolación.
- **Ranking**: heurística de diseño (O₂ 25, presión 10, combustible 20, seguridad 20, datos 15, gravedad 10), no validada por expertos. Un dato desconocido puntúa 0,4: no suma como uno verificado. La confianza del puntaje baja con cada dato desconocido.
- **Interpretación**: SI determinista (reglas sobre el desglose), no un LLM.

## Análisis de Frontera de Pareto para priorización de experimentos
`GET /api/v1/investigaciones/pareto` coloca cada investigación en un plano **evidencia (x, 0-100) × riesgo (y, 0-100)**.

- **Riesgo**: índice del modelo (sintético, no validado) en el punto de operación de la investigación. Lo declarado se usa tal cual; lo desconocido se infiere del entorno objetivo y se marca en `inferidos`. `[y_bajo, y_alto]` evalúa las 4 esquinas de la caja de incertidumbre (campo desconocido = dominio completo).
- **Evidencia**: O₂ 25 + presión 20 + flujo 10 + datos en PSI 30 + gravedad 15 (pesos de diseño). Desconocido aporta 0; nunca se inventa.
- **Dominancia**: A domina a B si riesgo(A) ≥ riesgo(B) y evidencia(A) ≤ evidencia(B) con una desigualdad estricta. Capa 1 = frontera (las más críticas); capas siguientes por ordenamiento no dominado.
- **Prioridad** = riesgo × (1 − evidencia/100); **codo** = mayor prioridad de la frontera; **hipervolumen** = fracción del plano dominada (baja al llegar datos).
- JSON para dibujar: `ejes`, `cortes`, `puntos[{id,x,y,y_bajo,y_alto,capa,en_frontera,cuadrante,prioridad,inferidos,evidencia_detalle,lectura}]`, `frontera[]`, `linea_frontera[{x,y}]` (escalera), `codo`, `hipervolumen`, `metodologia`, `supuestos`.
- Límite: el modelo se calibró con sólidos; gas/aerosol/gotas llevan `extrapolacion_combustible: true`.

## Consola de Investigaciones
- **Pareto**: rejilla 5×5 por investigación sobre P10–P90; `riesgo_medio`, `p_frontera` (Monte Carlo, semilla 20261113) y `dominados`. Eje Y elegible (riesgo, relevancia, incertidumbre). No es una validación: es incertidumbre del modelo sintético.
- **Mapa**: `GET /api/v1/mapa-riesgo` devuelve rejilla, anclas y `cobertura` (solo investigaciones con O₂ y presión conocidos); la sonda llama a `/predict` con las condiciones fijas del mapa.
- **Hardware**: `/hardware/ping` (contrato de 3 campos) y `/hardware/lectura` (lectura + historial). Solo un termopar (`--campo reaccion`) puede mover el gemelo.
- **Datos nuevos**: `/investigaciones/estado` expone `huella`; el frontend la sondea cada 5 s y repinta. Clasificación (familia, combustible, áreas) de fichas nuevas sigue siendo manual.
