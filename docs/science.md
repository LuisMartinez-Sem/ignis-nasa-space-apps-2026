# Base científica y límites

## Qué es real y qué es hipótesis
| Componente | Estado |
|---|---|
| Tendencia cualitativa de propagación (máximo a flujo intermedio, caída por extinción radiativa a flujo bajo y por soplado a flujo alto, sube con O2) | Basada en la literatura de propagación de llama sobre sólidos delgados en microgravedad |
| Constantes numéricas (`VELOCIDAD_REFERENCIA_MM_S` = 3,79, `FACTOR_CONCURRENTE` = 1,28) | **Calibradas** a 2 anclas de Saffire-I (1,8 y 1,3 mm/s). Ajuste, no validación |
| Ventana de Cool Flame (550–800 K = semimáximo; centro 675 K, ancho 150 K) | Ajustada a la ventana citada de FLEX (Nayagam, no verificada por IGNIS); la forma interior es hipótesis |
| Pesos del índice de riesgo | Diseño de producto; validar con expertos en seguridad contra incendios |

## Ruta de calibración
1. Descargar series de PSI (Saffire, FLEX, BASS) y unificarlas al esquema de `data/README.md`.
2. `IGNIS_RUTA_DATASET_CSV=... IGNIS_REENTRENAR_AL_INICIAR=true`.
3. Reemplazar la ventana heurística de `src/cool_flame.py` por un clasificador entrenado con datos FLEX/BASS.
4. Comparar métricas hold-out reales contra las sintéticas y reportarlas en el pitch.

## Limitaciones conocidas
- Dos regímenes (opuesto / concurrente). El factor concurrente (×1,4) se inspira en Saffire-I (1,8 vs 1,3 mm/s, confianza **media**: presentación, no NTRS). 1 g y O₂ > 50 % están fuera de dominio y se marcan.
- Todas las señales del detector temporal son sintéticas (generador propio): la precisión del 99,9 % por muestra mide el generador, no la física. Recalibrar con series FLEX/BASS.
- La incertidumbre del RF es dispersión entre árboles; la del ensemble profundo es aleatoria + epistémica y se reporta su ECE, pero ninguna está calibrada con datos reales.
- Las acciones sugeridas son reglas deterministas de apoyo; no sustituyen los procedimientos de misión.

## Dominio operativo
| Variable | Rango | Razón |
|---|---|---|
| Fracción de O₂ | **0,16 – 0,40** | La ISS opera ~0,21–0,241. Bajo 0,16 no hay combustión sostenida. 0,40 es el límite de emergencia en atmósferas de baja presión. |
| Presión | **35 – 101,325 kPa** | Atmósfera estándar como tope (la revisión propuso 101,0, pero eso rechazaría los 101,3 kPa nominales de la ISS). La Soyuz histórica operaba ~34 kPa. |
| Flujo, T ambiente, espesor | sin cambio | Validados. |

Fuera de esos rangos la API responde 422. En el 10 % superior del O₂ (> 0,36) o con presión < 40 kPa la respuesta
incluye una advertencia de extrapolación (confianza reducida). Las atmósferas históricas fuera de dominio (Apollo 1:
O₂ 100 %, 115 kPa) se describen con `CondicionesHistoricas` y **no se evalúan con el modelo**: se informa qué
variables exceden el dominio en lugar de extrapolar un número sin base física.

## Índice de riesgo (revisado)
`índice = 100 · (0,55 · P(propaga) + 0,30 · tanh(v / 10 mm/s) + 0,15 · P(llama fría))`

- **Pesos**: la probabilidad de propagar baja de 0,60 a 0,55 y la velocidad sube de 0,25 a 0,30: la velocidad dicta
  cuánto tiempo hay para reaccionar.
- **`tanh` en lugar de `min(v/10, 1)`**: el tope duro igualaba 10 y 100 mm/s y creaba una esquina artificial. Con `tanh`
  la severidad satura de forma gradual (0,76 a 10 mm/s; 0,96 a 20 mm/s) y velocidades de 1–2 mm/s, típicas en
  microgravedad, aportan ≈ 0,1–0,2 de severidad.
- Los pesos y los 10 mm/s de referencia son **decisiones de diseño**, no resultados ajustados: validarlos con
  expertos en seguridad contra incendios (ver `docs/validacion_externa.md`).

## Variables no incluidas (hoja de ruta)
Disponible también en `GET /api/v1/modelo/variables_no_incluidas`.

| Variable | Por qué importa | Prioridad |
|---|---|---|
| Geometría del confinamiento | Pasillo estrecho vs. módulo amplio cambia la dinámica de flujo | Alta |
| Orientación del material vs. flujo | Flujo concurrente vs. opuesto determina el modo de propagación (hoy solo categoría) | Alta |
| Historial de ignición | Fuente puntual (cortocircuito) vs. calentamiento general | Media |
| Composición detallada | Densidad, conductividad térmica, calor de gasificación | Media |

## Por qué TCN y no alternativas
| Enfoque | Veredicto |
|---|---|
| **TCN sobre sensores** | Ideal para alerta temprana en tiempo real: datos continuos con patrón temporal, causal (no usa el futuro), ≈1 ms por muestra en CPU. |
| Visión por computadora | Útil para validación offline; no para alerta en vivo (requiere línea de visión y es costosa). La llama fría además no emite luz visible. |
| Espectroscopía | Detecta especies químicas, pero es compleja y costosa para una nave. |
| **Conclusión** | Un híbrido TCN + sensores es el más robusto para la seguridad de la tripulación; la visión queda como confirmación. |

## Referencias consultadas (verificar antes de citar)
- NASA NTRS 20170002628 (Saffire, Ruff & Urban) · 20170008805 (ICES 2017) · 20160010292 (Saffire-II) · 20210011521 (Saffire-IV/V).
- Ferkul, *The Saffire Experiment*, 2017 US National Combustion Meeting (fuente de 1,8 / 1,3 mm/s; confianza media).
- Incidentes: ver `docs/incidentes.md`.

## Evento frente a potencial latente (HUD)
El índice de riesgo mide la **severidad condicionada a que haya ignición** (probabilidad de propagar, velocidad de llama,
llama fría). Con aire de la ISS y combustible delgado ya da un valor alto aunque no haya fuego. Por eso el HUD solo
muestra ALERTA/CRÍTICO cuando hay **evento**: reacción térmica ≥ 50 K sobre el ambiente o alarma del detector TCN.
Sin evento muestra NOMINAL y "potencial latente N". El valor numérico del modelo no se altera.

## Anclas y calibración
- `data/anclas_reales.json`: 6 anclas. Entrenan 3 (Saffire-I concurrente 1,8 mm/s, opuesto 1,3 mm/s, ventana FLEX 550–800 K); 3 son solo referencia (Saffire-II silicona 1-g, tiempos de combustión 420 s y 70 s) porque no son velocidades en el régimen del modelo.
- `generar_dataset_sintetico` reemplaza 40 filas por ancla (jitter 1,5 %, ruido 5 %); el total sigue en 6000.
- Constantes recalculadas analíticamente: `VELOCIDAD_REFERENCIA_MM_S` 8,0 → 3,7905 y `FACTOR_CONCURRENTE` 1,4 → 1,2802.
- **Renormalización del índice**: `tanh(v/10)` → `tanh(v/4,74)`. Con la ley calibrada y 10 mm/s, el nivel CRÍTICO era inalcanzable (índice máx. ≈ 71). Para revertir: devolver 10 en `src/predictor.py`, `frontend/js/paleta.js` y el aria-label de `frontend/index.html`.
- Error en Saffire-I: 193 % → 0,9 % (`linea_base_saffire.json`). Las anclas están en el entrenamiento: **calibración, no validación**.

## Justificación de pesos (55/30/15)
55 % Probabilidad (factor determinante de propagación), 30 % Velocidad (criticidad temporal para la evacuación), 15 % Cool Flame (riesgo invisible residual). Son pesos de diseño de producto, no ajustados a datos: pendientes de validación por expertos en seguridad contra incendios.
