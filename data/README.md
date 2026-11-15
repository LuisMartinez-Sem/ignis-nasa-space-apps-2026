# Datos de IGNIS

## Fuentes oficiales
- **PSI** (psi.nasa.gov): Saffire, FLEX, BASS.
- **NTRS** (ntrs.nasa.gov): papers técnicos para calibración.
- **NASA Image and Video Library** (images.nasa.gov): media.

## Estado actual
Hasta cargar datos reales, IGNIS entrena con un **dataset sintético semi-empírico**
(`src/dataset_sintetico.py`). Es un andamio cualitativo, **no** datos NASA.
Toda respuesta de la API informa `origen_datos` para que nunca se confunda.

## Formato del CSV real (`data/raw/*.csv`)
Una fila por observación (p. ej. por tramo de propagación medido en un experimento).

| Columna | Unidad | Rango válido |
|---|---|---|
| `fraccion_o2` | fracción molar | 0.16 – 0.40 |
| `velocidad_flujo_cm_s` | cm/s | 0 – 100 |
| `presion_kpa` | kPa | 35 – 101.325 |
| `temperatura_ambiente_k` | K | 250 – 400 |
| `espesor_combustible_mm` | mm | 0.01 – 10 |
| `material` | texto | `sibal`, `pmma`, `celulosa` |
| `velocidad_propagacion_mm_s` | mm/s | 0 – 200 (0 = extinción) |

Activar: `IGNIS_RUTA_DATASET_CSV=data/raw/tu_archivo.csv` y `IGNIS_REENTRENAR_AL_INICIAR=true`.

Dominio operativo: O₂ > 0.36 o presión < 40 kPa emiten advertencia de extrapolación. Las atmósferas históricas
fuera de dominio (p. ej. Apollo 1, O₂ 100 %) **no** se evalúan con el modelo (`CondicionesHistoricas`).

## Datos PSI (`data/raw/psi/<experimento>/`)
Coloca aquí CSV, HDF5 o JSON de PSI, una carpeta por experimento (`saffire-i`, `saffire-ii`, `saffire-iii`, `bass`,
`bass-ii`, `flex`, `flex-2`, …). `make psi-ingestar` detecta formatos, convierte unidades (SI/imperial), reporta
cobertura y versiona el dataset con SHA-256 en `data/versiones/`. Guía completa: `docs/psi_integracion.md`.
FLEX/CFI (llama fría) se reportan pero **no** entran al modelo de propagación sobre sólidos.
