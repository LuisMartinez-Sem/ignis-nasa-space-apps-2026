# Guía de ingesta de datos nuevos

Qué hacer si la NASA publica archivos con un formato distinto de `data/investigaciones.json`. Todo lo descrito aquí se probó con archivos de ejemplo (ver «Ejemplos reales de salida»); lo que **no** se ha podido probar (los archivos reales de PSI) está marcado.

## 0. Principio de seguridad
La API **nunca** depende de que la ingesta salga bien. Si algo falla, el catálogo actual (o el respaldo hardcodeado de las 19 investigaciones) sigue sirviéndose y el HUD no se entera. Un archivo malo se omite y se reporta; no se adivina nada.

## 1. Procedimiento (5 minutos)
1. Copiar los archivos a `data/raw/` (con Docker: la carpeta `./data/raw` ya está montada en el contenedor).
2. Ejecutar:
   ```bash
   python scripts/ingestar_datos_nasa.py            # Docker: docker compose exec ignis python scripts/ingestar_datos_nasa.py
   ```
3. Leer el resumen de la consola (una línea por archivo) y, si hace falta, el detalle en `data/processed/investigaciones_ingestadas_reporte.json`.
4. Abrir el HUD → Investigaciones. **No hay que reiniciar**: la API relee la superposición `data/investigaciones_ingestadas.json` al cambiar. El estado del catálogo (`estado.ingesta_aplicada` en `GET /api/v1/investigaciones`) lista qué investigaciones se actualizaron.
5. Repetir el comando es seguro (es idempotente por hash). `--forzar` reprocesa todo; `--estricto` devuelve código de salida 1 si algún archivo falla (útil en scripts).

## 2. Cómo se mapea
El script acepta **CSV** (separador `, ; tab |` detectado solo) y **JSON** (una lista de objetos, o un objeto que contiene una lista). Cada columna se reconoce por sinónimos (sin acentos, mayúsculas ni signos; lo que va entre paréntesis se usa como unidad):

| Campo del catálogo | Nombres de columna reconocidos (ejemplos) | Unidades |
|---|---|---|
| Investigación (**obligatoria**) | `investigation`, `experiment`, `name`, `id`, `acronym`, `study`, `investigacion`, `nombre` | se busca por `id`, `nombre` o `nombre_completo` del catálogo |
| O₂ | `O2 (%)`, `oxygen_percent`, `o2_fraction`, `oxigeno` | `%` o **fracción** si el nombre dice `fraction/fraccion`; sin pista y valor ≤ 1 → se **omite** por ambiguo |
| Flujo | `flow (cm/s)`, `airflow (m/s)`, `flujo (mm/s)` | cm/s, m/s, mm/s → cm/s |
| Presión | `Pressure (psi)`, `pressure_kPa`, `presion (atm)` | kPa, psi, Pa, atm, bar → kPa (1 psi = 6.894757 kPa) |
| Hardware / objetivos / combustible / instalación | `hardware`, `objectives`, `fuel`, `facility`… | texto (máx. 600 caracteres) |

Reglas que conviene conocer:
- Varias filas de la misma investigación se agregan como **rango** (mín–máx).
- Un valor que el catálogo ya conoce **no se sobrescribe**: si el archivo difiere, se registra un `CONFLICTO` y se conserva el catálogo (se decide a mano, ver §4).
- Un campo que antes era desconocido pasa a conocido y sale de `campos_no_verificados`; el ranking y el Pareto lo reflejan y la confianza sube.
- Una unidad no reconocida **no se asume**: la columna se omite (`OMITIDO: unidad de presión no reconocida en 'Chamber P'`).
- **El script no rellena `datos_en_psi`** (dato clave del ranking y del Pareto). Se edita a mano en `data/investigaciones.json` (§4) cuando se confirme qué experimentos tienen datos publicados.

## 3. Qué pasa si falla (cada caso se probó)
| Situación | Resultado en consola / reporte | La API |
|---|---|---|
| Archivo ilegible o binario con extensión `.json` | `[fallido] … 'utf-8' codec can't decode…` | Sin cambios |
| Sin columna que identifique la investigación | `[fallido] … sin columna de identificación…` | Sin cambios |
| Columnas con nombres no reconocidos (`Oxygen Level`, `Chamber P`) | `[sin_coincidencias]` y la lista `columnas_ignoradas` en el reporte | Sin cambios |
| Investigación que no está en el catálogo (p. ej. `ZZZ-nuevo`) | aparece en `no_mapeadas`; el resto del archivo sí se aplica | Se aplica lo reconocido |
| Valor distinto del que ya tiene el catálogo | `CONFLICTO: … (se conserva el catálogo)` | Se conserva el catálogo |
| `data/investigaciones_ingestadas.json` corrupto | se registra el error y se ignora la superposición | Sirve el catálogo base |
| `data/investigaciones.json` borrado o corrupto | `estado.origen = "respaldo"` | Sirve las 19 investigaciones hardcodeadas |
| Formatos que el script **no** lee: HDF5, imágenes, video | no se procesan (solo `.csv` y `.json`) | Sin cambios |

> Los datos crudos de PSI (HDF5, imágenes/video) se manejan con el flujo aparte `make psi-inspeccionar` → `make psi-ingestar` (ver `docs/psi_integracion.md`). **No verificado con archivos reales de PSI**; convertir imágenes/video en velocidades de llama no está implementado.

## 4. Si el formato es diferente y no se reconoce
Elegir **una** opción, de menor a mayor esfuerzo:

**A. Renombrar columnas en una copia del archivo** (1 minuto, sin tocar código). Poner la unidad entre paréntesis: `Chamber P (kPa)`, `Oxygen Level (%)`, y `Experiment` para la investigación.

**B. Añadir un sinónimo** en `scripts/ingestar_datos_nasa.py`, diccionario `SINONIMOS` (es una expresión regular sobre el nombre normalizado: minúsculas, sin acentos ni signos). Ejemplo para `Oxygen Level` → `oxygenlevel`:
```python
"o2": re.compile(r"^(o2|oxygen|oxigeno)(percent|pct|porcentaje|fraction|fraccion|concentration|concentracion|volpct|mole|molefraction|level)?$|^(o2|oxygen|oxigeno)$"),
```
Para presión (`Chamber P` → `chamberp`) añadir `chamberp` a la alternativa inicial y poner la unidad en el nombre de la columna (si no, se omite). Probar con `python scripts/ingestar_datos_nasa.py --forzar`.

**C. Editar el catálogo a mano** (siempre disponible y es la fuente de verdad):
1. Editar `data/investigaciones.json` (poner el valor, `"datos_en_psi": true`, y quitar el campo de `campos_no_verificados`).
2. Regenerar el respaldo para que no derive: `python scripts/regenerar_respaldo.py`.
3. Comprobar: `python -m pytest tests/test_investigaciones.py tests/test_robustez.py` (hay un test que falla si el respaldo y el archivo no coinciden).
4. Con Docker, reconstruir la imagen (`docker compose up --build`) o montar el archivo.

**D. Revertir todo**: borrar `data/investigaciones_ingestadas.json`. La API vuelve al catálogo base sin reiniciar.

## 5. Ejemplos reales de salida
Archivo `formato_a.csv` (`Experiment,O2 (%),Pressure (psi),Flow (cm/s),Apparatus`):
```
[ok] formato_a.csv · actualizadas: bass, saffire-iii · no_mapeadas: ZZZ-nuevo
```
`bass` queda con O₂ 25–35 %, flujo 5–10 cm/s y presión 101.35 kPa (14.7 psi). Con `Study,Oxygen Level,Chamber P`: `[sin_coincidencias]` + `columnas_ignoradas: ["Oxygen Level", "Chamber P"]` → aplicar la opción A o B.

## 6. Después de ingerir
- Revisar `GET /api/v1/investigaciones/pareto`: los puntos se desplazan a la derecha (más evidencia) y el riesgo deja de ser idéntico para casi todas.
- Anotar en el pitch qué datos son **reales** (con archivo de origen, campo `fuente`) y cuáles siguen siendo del catálogo del equipo.
- Lo que sigue sin poder comprobarse: validez del modelo sintético con datos de PSI, hasta que alguien contraste las predicciones contra mediciones.

## 7. Puente Arduino
`hardware_bridge.py` (raíz) envía la temperatura serial a `/api/v1/predict`; ver su cabecera. La temperatura es la única magnitud medida: O₂, presión y flujo son valores declarados.
