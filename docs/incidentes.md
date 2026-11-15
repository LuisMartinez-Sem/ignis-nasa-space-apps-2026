# Simulador de incidentes históricos

`GET /api/v1/incidentes` · `GET /api/v1/incidentes/{id}` · `GET /api/v1/incidentes/{id}/simular`

Los datos viven en `data/incidents/*.json` y se validan con Pydantic (`src/incidentes_historicos.py`).
**Ningún dato histórico está en el código.** Un JSON inválido se omite sin tumbar el catálogo.

## Reglas de honestidad (decisiones de diseño)
1. Cada hecho trae `confianza` (documentado · aproximado · no_verificado · ilustrativo · modelo · supuesto) y `fuente`.
2. Lo que no está documentado tiene `t_s = null` ("sin hora"). No se inventan tiempos.
3. La comparación es un **contrafactual**: *ventana de oportunidad vs. latencia de reacción de IGNIS*.
   No se afirma "N veces más rápido": no existe una medición humana comparable.
4. La telemetría de Mir es **ilustrativa** y está marcada así en cada punto.

## Los cuatro casos
| id | Qué es | Qué se compara |
|---|---|---|
| `mir-1997` | Incendio del SFOG en Kvant-1 | Reacción de IGNIS (detector sobre traza sintética) vs. duración documentada del fuego (≈90 s según NASA Shuttle-Mir; «14 min» solo en fuentes secundarias, marcado *no verificado*) |
| `apollo1-1967` | Incendio en cabina con O₂ puro, **1 g** | Riesgo de la atmósfera ANTES de la ignición. Marcado **fuera de dominio** (el modelo es de microgravedad y O₂ ≤ 50 %) |
| `iss-2015-falsa-alarma` | Falsa alarma de **amoníaco** (no fue fuego ni humo) | Análogo de discriminación de falsos positivos: pico aislado en un sensor |
| `saffire-2016-2024` | Experimentos controlados de NASA | Predicción del modelo vs. medición publicada (solo Saffire-I tiene velocidades en las fuentes consultadas; confianza media) |

## Correcciones a datos que circulan
- «Mir: 14 min» **no** figura en la fuente NASA primaria consultada (≈1,5 min de llama; humo 5–20 min).
- «ISS 2015» fue una falsa alarma de amoníaco por un multiplexor (MDM), no un incendio.
- «105× más rápido» no es defendible: se sustituyó por la ventana de oportunidad.

## Añadir un incidente
Copiar un JSON existente del mismo `tipo`, cambiar `id` (`^[a-z0-9][a-z0-9-]{2,59}$`), fuentes y eventos,
y ejecutar `pytest tests/test_incidentes.py`. El validador exige fuentes existentes, telemetría ordenada
y los datos requeridos por tipo.
