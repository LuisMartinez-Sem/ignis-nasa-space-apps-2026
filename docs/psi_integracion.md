# Integración de datos de PSI: estrategia

> **Pivote.** Los CSV que se descargan de PSI son **índices de experimentos** (metadatos, ~4 filas por experimento), **no datasets**.
> Los datos crudos son **ZIPs de imágenes/video**: para obtener una velocidad de propagación hay que **procesarlos**
> (video → posición del frente → mm/s), un trabajo de visión por computador que IGNIS no ha hecho.
> Por eso IGNIS **no entrena con datos de PSI**. Usa un **dataset sintético semi-empírico (6000 filas) calibrado con valores
> publicados** (anclas en `data/anclas_reales.json`) y deja el pipeline de ingesta **listo para una ingesta futura**.

## Qué es cada cosa

| Elemento | Estado |
|---|---|
| CSV de PSI | Índice de experimentos. No sirve para entrenar. |
| ZIPs crudos de PSI | Imágenes; requieren procesamiento. No procesados por IGNIS. |
| Dataset de entrenamiento | Sintético, 6000 filas en total; 40 filas por ancla de entrenamiento reemplazan a las últimas. |
| Anclas de entrenamiento | Saffire-I 1,8 mm/s (concurrente) y 1,3 mm/s (opuesto); ventana FLEX 550–800 K. |
| Anclas de referencia (no entrenan) | Saffire-II silicona 1-g (1,2 mm/s); tiempos de combustión Saffire-I (420 s y 70 s), de otro régimen/magnitud. |
| Pipeline de ingesta (`src/ingesta_psi.py`, `lector_psi.py`) | Probado con **mocks**; no se ha ingerido ninguna fila real. Sin cambios en esta versión. |

## Calibración, no validación

Las anclas están **dentro** del entrenamiento: el error de Saffire-I bajó de **193 %** (sin calibrar) a **0,9 %** porque el
modelo se ajustó a esos dos puntos. Es un **ajuste**, no una validación independiente. La validación contra tablas de NTRS sigue en curso.

## Fuentes (no verificadas por IGNIS)

- Saffire-I: cifras aportadas con la fuente indicada NTRS 20170002628; IGNIS solo las localizó en una presentación de Ferkul (UCL).
- Saffire-II (PSI-99) y tiempos de combustión (PSI-98): indicados por el equipo; el CSV no se reprodujo aquí.
- FLEX: ventana de llama fría 550–800 K según Nayagam. **DOIs: pendientes de aportar por el equipo; no se inventan.**

## Para una ingesta futura (el pipeline sigue siendo válido)

## 1. Descarga paso a paso
1. Portal: <https://science.nasa.gov/biological-physical/data/> (redirige desde psi.nasa.gov). Regístrate; la aprobación llega por correo (≈24 h). **Hazlo hoy.**
2. Búsqueda: `https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation` → abre la investigación
   (`.../repo/data/investigations/PSI-<n>`, página renderizada con JavaScript) → pestaña de datos.
3. Descarga CSV/HDF5/JSON por archivo, o el `.zip` masivo que ofrece el repositorio.
4. Copia a `data/raw/psi/<experimento>/` (`saffire-i`, `saffire-ii`, `saffire-iii`, `bass`, `bass-ii`, `flex`, `flex-2`, `cfi`), o deja que el script lo haga:
   ```bash
   make psi-descargar                      # menú interactivo: pregunta el experimento y muestra los pasos
   python -m scripts.descargar_psi --experimento bass --url <ENLACE.zip> --sha256 <HUELLA>   # enlace recibido de PSI
   python -m scripts.descargar_psi --lista --prefijo DSI/                                    # explorar el bucket público
   ```
   El script solo usa HTTPS y hosts permitidos, verifica SHA-256 (si lo das) o tamaño+MD5/ETag (S3), extrae zips con
   protección zip-slip/zip-bomb y anota cada archivo en `descargas.json` (trazabilidad de lo crudo).
5. Si un enlace responde 401/403, el script lo dice y remite a este registro: no hay forma de saltarlo.

## 2. Qué experimentos y por qué
| Prioridad | Experimento | Rol en IGNIS | Motivo |
|---|---|---|---|
| 1 | **BASS / BASS-II** | `propagacion` | Sólidos en flujo de baja velocidad con variación de O₂, flujo, espesor: lo más parecido al modelo de propagación. |
| 2 | **Saffire I–III** | `propagacion` | Escala real (mayor muestra de SIBAL en microgravedad) y es lo que valida el HUD (incidente Saffire). |
| 3 | **FLEX / FLEX-2 / CFI** | `llama_fria` | Gotas y llamas frías: calibran `cool_flame` y el detector TCN. **No** alimentan la propagación en sólidos (se reportan, no entran al entrenamiento). |

## 3. Variables necesarias y mapeo al esquema de `data/README.md`
Columnas reconocidas por nombre (inglés/español) y unidad leída del archivo (atributo HDF5, bloque `units` JSON, o texto
"Pressure (psia)" en el encabezado). **Nunca se adivina una unidad**, salvo O₂ (≤ 1,5 ⇒ fracción; si no, %), que queda anotado como supuesto.

| Esquema IGNIS | Nombres típicos en PSI | Unidades aceptadas |
|---|---|---|
| `fraccion_o2` | O2, oxygen, oxígeno | fracción, %, vol% |
| `velocidad_flujo_cm_s` | flow, air speed | cm/s, m/s, ft/s, in/s |
| `presion_kpa` | pressure, p, presión | kPa, Pa, psi/psia, atm, bar, mbar |
| `temperatura_ambiente_k` | ambient/bulk/chamber/cabin temp | K, °C, °F |
| `espesor_combustible_mm` | thickness | mm, µm, m, mil, in |
| `velocidad_propagacion_mm_s` | spread/flame speed/burn rate | mm/s, cm/s, m/s, in/s, ft/s |
| `material` | material, fuel, sample | `sibal`, `pmma`, `celulosa` (por defecto del experimento si falta) |
| `regimen_flujo` (opcional) | concurrent/opposed, flow direction | concurrente / opuesto |

**Advertencia de ciencia:** los archivos crudos de PSI suelen traer series temporales de sensores y **no** una columna de
velocidad de propagación lista; esa magnitud suele salir de los reportes (NTRS) o de procesar video/termopares. Si falta,
el experimento se **omite con el motivo** en el reporte de cobertura; hay que derivarla o crear un `mapeo.json` propio.

Mapeo manual (cuando la inferencia no basta): `data/raw/psi/<exp>/mapeo.json` con la estructura de `MapeoCSV`
(`columnas: {canónica: {columna, unidad}}`, `material` o `material_fijo`, `regimen_fijo`, `id_experimento`).

## 4. Ingesta, cobertura y versión
```bash
make psi-ingestar        # = python -m src.pipeline_datos psi
```
- Detecta CSV/HDF5/JSON, ignora el resto (con aviso), convierte a SI y descarta filas fuera de dominio contando el motivo.
- **Reporte de cobertura por experimento**: archivos leídos/omitidos (con razón), filas crudas/válidas, variables mapeadas,
  rangos observados, supuestos. Se guarda como `cobertura_psi.json` junto a la versión.
- Versión inmutable en `data/versiones/<fecha>_<hash8>/` (`datos.csv`, `manifiesto.json`, SHA-256). La partición
  entrenamiento/prueba es **por experimento** (`id_experimento`) para evitar fuga de información.

## 5. Reentrenar, comparar y actualizar el pitch
```bash
make psi-reporte                       # fija la línea base: error de Saffire-I del modelo sintético
python -m src.entrenamiento --version <id>
make psi-reporte VERSION=<id>          # RF vs profundo con datos reales + línea del pitch
```
Genera `modelos/comparativa_real.json`, `docs/comparativa_real.md` y reescribe la línea de `docs/pitch.md` con cifras calculadas:
"Modelo entrenado con X filas de Saffire, Y de FLEX, Z de BASS. Recalibración en curso. Error Saffire-I reducido de A% a B%."
Mientras no haya filas reales aparece `0` y `[?]%`: **no se escribe ninguna cifra a mano.** Con pocas filas reales
(< 200) el reporte avisa de alta varianza.

## 6. Pruebas
`tests/test_ingesta_psi.py`, `tests/test_descargar_psi.py`, `tests/test_reporte_psi.py` cubren formatos, unidades imperiales/SI,
cobertura, versionado, integridad, zip-slip y la línea del pitch, todo sobre datos simulados (sin red).
