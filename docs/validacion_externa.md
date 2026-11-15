# Validación externa

Estado: **pendiente**. El HUD muestra el badge "Validación pendiente" hasta que exista un validador. Para activarlo, edita
`frontend/validacion.json` (`{"validador": "Nombre, cargo, institución"}`); el badge pasará a "Validado por …".
Solo registra a alguien que haya revisado y aceptado ser citado.

## 5 preguntas para un físico/ingeniero de combustión
1. ¿Es razonable el dominio operativo (O₂ 16–40 %, 35–101,325 kPa, flujo 0–100 cm/s) para una cabina tripulada, y los avisos de extrapolación (O₂ > 0,36; P < 40 kPa)?
2. ¿Es defendible que la velocidad de propagación en sólidos delgados dependa así de O₂, flujo y espesor (tendencia cualitativa), sabiendo que hoy es un modelo semi-empírico sintético?
3. ¿Sirve la temperatura de reacción (centro ≈ 675 K, ancho ≈ 150 K; 550–800 K es el semimáximo, más probable a baja presión) como indicador de llama fría? ¿Qué canal añadirías (p. ej. CO, formaldehído, IR de banda)?
4. ¿Es razonable el índice 100·(0,55·P(propaga) + 0,30·tanh(v/10 mm/s) + 0,15·P(llama fría)) como severidad *condicionada a ignición*, y el criterio de "evento" (ΔT ≥ 50 K o alarma del detector)?
5. ¿Qué variables físicas faltan antes de usarlo como apoyo real (ver `GET /api/v1/modelo/variables_no_incluidas`) y cuál priorizarías?

## Formulario de revisión (rellenar una vez por validador)
| Campo | Respuesta |
|---|---|
| Nombre, cargo, institución | |
| Fecha de la revisión | |
| Material revisado (docs/science.md, código, HUD, resultados) | |
| **Revisado** (qué se leyó/ejecutó) | |
| **Aprobado** (qué considera correcto) | |
| **Sugerido / corregir** (qué cambiaría) | |
| **Rechazado** (qué no debe afirmarse) | |
| ¿Acepta ser citado? (sí/no, con qué texto exacto) | |

## Plantilla para citar al validador en el pitch
> "La física del modelo fue **revisada** por [Nombre, cargo, institución] el [fecha]. Aprobó [alcance aprobado] y sugirió
> [sugerencia principal], ya incorporada / en progreso. No avaló [límite explícito]."

Regla: no escribir "validado" si el validador solo revisó una parte; citar exactamente el alcance que aprobó.
