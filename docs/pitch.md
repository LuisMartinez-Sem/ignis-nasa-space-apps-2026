# Pitch (3 min) — IGNIS · *Flame in Freefall*

**Problema.** En microgravedad la llama es esférica, lenta… y existe una **llama fría** sin luz visible que una cámara
normal no ve y que puede reavivarse. Los detectores clásicos dependen de un solo canal.

**IGNIS.** Un copiloto que (1) estima el riesgo de propagación con incertidumbre, (2) **detecta la reacción en sus
primeras décimas de segundo** fusionando 6 sensores, y (3) explica por qué.

**Demostración (en este orden).**
1. Monitor → *Dividido*: mitad cámara visible, mitad IR. A la izquierda se ve la llama fría; a la derecha, nada.
2. Detector temporal: señal «Llama caliente» → alarma en ≈0,7 s; «Pico de un sensor» → no escala.
3. Copiloto: «lo que más mueve el riesgo ahora: O₂» y el acuerdo/desacuerdo RF vs. profundo.
4. Incidentes → Mir: ventana de oportunidad de ≥90 s frente a una reacción de IGNIS de <1 s (contrafactual, con fuentes).

**Números que SÍ podemos defender** (señales y datos **sintéticos**; ver límites):
| | IGNIS (TCN) | Umbral fijo 30 K | Umbral 60 K | Cámara visible |
|---|---|---|---|---|
| Detección global | 100 % | 99,4 % | 93,3 % | 58,2 % |
| Falsas alarmas / h | 0 | 8,1 | 0 | 5,3 |
| Tiempo a detección, llama fría (mediana) | 0,7 s | 1,1 s | 1,7 s | 14,5 s |
| Tiempo a detección, llama caliente | 0,7 s | **0,5 s** | 0,6 s | 0,3 s |

IGNIS **no** es el más rápido en llama caliente (el umbral fijo gana 0,2 s): su ventaja es no dar falsas alarmas y ver la llama fría.

**Límites (decirlo antes de que lo pregunten).** Todo el ML se entrenó con datos sintéticos; las métricas validan la
mecánica y la latencia, no la física real. La calibración con PSI (FLEX/BASS/Saffire) es el siguiente paso y el pipeline
ya está listo (`docs/arquitectura.md`). En Saffire-I el error absoluto medio del modelo sintético es grande (cifra exacta abajo, calculada con `python -m src.reporte_psi`): es la brecha que los datos reales cierran.

**Dataset.** Sintético semi-empírico (6000 filas) calibrado con valores publicados en Saffire-I (1.8 mm/s concurrente, 1.3 mm/s opuesto) y FLEX (Cool Flames 550-800 K). Validación contra tablas de NTRS en curso.

**Cierre.** Los CSV de PSI son índices y los datos crudos son imágenes: el pipeline de ingesta queda listo para procesarlos (video → velocidad) en una fase futura.

<!-- PITCH_LINEA -->
**Modelo sin filas crudas de PSI. Calibrado con anclas publicadas de Saffire-I y FLEX. Error en Saffire-I: 193 % sin calibrar → 0,9 % tras calibrar con anclas (ajuste, no validación).**
<!-- /PITCH_LINEA -->
