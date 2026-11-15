# Cumplimiento del reto «Flame in Freefall» (NASA Space Apps 2026)

Matriz requisito por requisito, escrita sin inflar. Estados: **Cumple**, **Parcial**, **Pendiente** (depende de los datos del 13 de noviembre).
Texto del reto: <https://www.spaceappschallenge.org/> (los recursos y los datos PSI se publican el 13 de nov).

| Pide el reto | Estado | Qué hace IGNIS | Límite honesto |
|---|---|---|---|
| Tablero interactivo web que **resuma, ordene (rank) e interprete** investigaciones | Cumple | Consola con ranking 0-100 por entorno, desglose por componente e interpretación en texto (`/api/v1/investigaciones/ranking`) | La «SI» es determinista (reglas sobre el desglose), no un LLM. Heurística de diseño no validada por expertos |
| Identificar investigaciones relevantes para **ISS, Luna, Marte, rovers** | Cumple | Selector de entorno ISS / Luna / Marte / Traje; Marte usa la atmósfera lunar como **supuesto** (marcado) | El traje (100 % O₂, 29,6 kPa) está fuera del dominio del modelo y no se evalúa |
| **Extraer datos** para modelado predictivo | Cumple | Exportación CSV/JSON del catálogo y de las anclas; API de predicción documentada | Los metadatos reales de PSI aún no se han leído: lo desconocido se marca, no se rellena |
| **Resaltar** investigación para controles/equipo de seguridad de nueva generación | Parcial | Pareto riesgo × evidencia (qué investigar primero), huecos y «Del espacio a la Tierra» | La relación con cada área de seguridad es criterio del equipo, no de la NASA |
| Mostrar objetivos, combustibles, condiciones (O₂, flujo), variables, sensores | Parcial | Ficha por investigación y comparación visual (similitudes/diferencias) | Hoy solo 1 de 19 tiene O₂ y presión conocidos; el resto se completa con PSI |
| **Comparar** investigaciones | Cumple | Bandeja con botón ＋ (2-4), rejilla de barras y tabla de diferencias | — |
| Atmósfera **lunar** (≥ 30 % O₂, ≤ 10,2 psi) | Cumple | Base lunar vs ISS con pO₂, delta y supuestos; abrir en el Monitor | El modelo se entrenó con sintéticos calibrados; extrapola la gravedad parcial |
| **Datos de gravedad parcial** | Pendiente | Marcados como «desconocida»/«pendiente» (LUCI, FM2 aún no están en PSI, como dice el reto) | No hay datos: no se inventan |
| Aplicaciones **en la Tierra** (agua nebulizada, detectores, equipo de bomberos) | Cumple | Pestaña «Del espacio a la Tierra» con tarjetas y filtro del ranking | Vínculos con cada investigación = criterio del equipo |
| Entrada de **datos nuevos** | Cumple | CSV de prueba (reversible, marcado PRUEBA) y script de ingesta real; todo se actualiza solo (huella + sondeo) | La clasificación de familia/combustible/áreas de una ficha nueva es manual |
| Audiencia: estudiantes e ingenieros | Cumple | Demo guiada de 90 s, teclado y lectores de pantalla, reducir movimiento | Sin pruebas de usabilidad con usuarios reales |
| Fuera de alcance: cohetes y propelentes | Cumple | No se modela | — |

## Extras que el reto no pide
Gemelo digital 3D, detector temporal de llama fría, copiloto, simulador de incidentes históricos y puente con hardware (Arduino). Son **complemento**: la entrega se centra en la consola.

## Brechas que conviene cerrar antes del 14-15 de nov
1. Leer los metadatos reales de PSI y regenerar el catálogo (`docs/guia_ingesta.md`).
2. Revisión de la física por un especialista (`docs/validacion_externa.md`).
3. Decidir si se añade una capa de lenguaje natural opcional (LLM) sobre el catálogo; hoy la interpretación es por reglas.
4. Probar el puente con el Arduino real y `docker build`.
