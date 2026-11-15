# IGNIS — contexto completo para explicarlo y defenderlo

## 1. Qué es, en una frase
IGNIS es un **dashboard de seguridad contra incendios en el espacio**: ordena las investigaciones de combustión en microgravedad de la NASA, mide qué riesgo implica cada atmósfera (ISS, base lunar, Marte, traje) y dice **cuánto se puede creer** cada cifra. Además trae un Monitor (gemelo digital + detector + copiloto) y un reproductor de incidentes históricos.

Reto: *Flame in Freefall* (NASA Space Apps 2026). Lo central es el **Dashboard (pestaña Investigaciones)**; Monitor e Incidentes son apoyo.

## 2. Recorrido del Dashboard (qué decir en cada pestaña)
| Pestaña | Qué muestra | Cómo explicarlo |
|---|---|---|
| **Ranking** (izquierda) | 19 investigaciones del catálogo, ordenadas por relevancia para el entorno elegido (ISS/Luna/Marte/Traje). | Puntaje 0-100 = suma ponderada: O₂ 25, presión 10, combustible 20, áreas de seguridad 20, datos en PSI 15, gravedad 10. Lo desconocido puntúa 0,4 (neutro-bajo), nunca se rellena. |
| **Análisis** | Por qué cada puntaje, ficha y campos no verificados. | Cada número se puede rastrear a un componente. |
| **Pareto** | Riesgo (eje Y) contra evidencia (eje X). | Ver sección 4. |
| **Mapa de riesgo** | Campo de color del índice según O₂ y presión, con cajas de lo que cada investigación probó. | El color es el índice del modelo; las cajas son cobertura experimental: donde no hay caja, nadie ha probado. |
| **Base lunar** | Compara la atmósfera lunar del reto (≥ 30 % O₂, ≤ 70,3 kPa) con la ISS. | Ver sección 5. |
| **Comparar** | Hasta 4 investigaciones lado a lado. | Similitudes y diferencias, como pide el reto. |
| **Confianza** | Informe de confianza por investigación (diferenciador). | Ver sección 6. |
| **Hoja de ruta** | Oportunidades abiertas en los datos NASA y siguiente paso de IGNIS. | Los límites se declaran y cada uno tiene versión y siguiente paso. |
| **Del espacio a la Tierra** | Laboratorio de la llama (0–1 g) y aplicaciones terrestres (agua nebulizada, detectores de humo, equipo de bomberos). | El origen de cada aplicación sale del texto del reto; la relación con las investigaciones es criterio del equipo. |

## 3. El modelo de riesgo (física y matemática)
- **Índice 0-100** = 100·(0,55·P(propaga) + 0,30·tanh(v/4,74) + 0,15·P(llama fría)).
  - 55 pts: probabilidad de que la llama se propague. 30 pts: velocidad de llama; `tanh` satura (duplicar la velocidad no duplica el riesgo; 4,74 mm/s es la escala). 15 pts: llama fría, que no aplica a estos sólidos.
  - Por eso **casi nunca llega a 100**: con 40 % de O₂ el techo práctico del modelo ronda 83.
- **Niveles**: 25 / 50 / 75 → Nominal, Precaución, Alerta, Crítico.
- **Calibración**: el modelo es sintético y semi-empírico, calibrado con anclas publicadas (Saffire-I: 1,8 mm/s en flujo concurrente y 1,3 mm/s en opuesto; FLEX: ventana de llama fría 550–800 K). **No** se entrenó con datos reales de PSI.
- **Dominio**: O₂ 16–40 %, presión 35–101,3 kPa, flujo 0–100 cm/s. Fuera de ahí (traje espacial, Apollo 1) IGNIS dice «fuera de dominio» y no evalúa.
- **Potencial latente**: sin evento, el índice es «el riesgo si hubiera ignición», no un incendio en curso.

## 4. Pareto: por qué y cómo leerlo
- **Por qué**: hay que decidir qué estudiar primero con datos incompletos. Dos criterios chocan (riesgo alto, evidencia baja); Pareto evita inventar un peso entre ellos.
- **Cada punto** = una investigación. X = evidencia 0-100 (pesos de diseño: O₂ 25, presión 20, flujo 10, datos en PSI 30, gravedad 15). Y = riesgo del modelo.
- **Frontera** (rojo): ninguna otra investigación es a la vez más riesgosa y peor documentada. No son «las peores»: son las que más urge cubrir. Hoy en la Luna: FM2 y LUCI.
- **Prioridad** = riesgo × (1 − evidencia/100). La mayor de la frontera es el «codo» (hoy FM2).
- **Hipervolumen** (Luna: 73 %; ISS: 63 %): fracción del plano riesgo × evidencia que queda «a la sombra» de las investigaciones. Alto = todavía hay mucho riesgo sin respaldo de datos. Baja cuando llegan datos reales. **No es un porcentaje de seguridad.**
- **×N** sobre un punto: N investigaciones comparten posición porque no declaran O₂/presión y IGNIS las evalúa en la atmósfera objetivo; al hacer clic se elige cada una.
- Los puntos con O₂ o presión inferidos muestran su **intervalo** (P10–P90 sobre una rejilla 5×5) y **P(frontera)** por Monte Carlo (semilla fija, reproducible).

## 5. Base lunar: por qué solo O₂ y presión
- Son las dos variables que el reto fija para el hábitat y las que más cambian la inflamabilidad. Flujo y material los eliges tú; espesor (0,2 mm) y temperatura (295 K) son valores de referencia.
- Muestra el índice desglosado (propagación + velocidad + llama fría) y qué porcentaje del resultado está verificado (O₂ y presión del reto) o supuesto.
- Con el preset del reto (30 %, 70 kPa) el índice es mayor que en la ISS: más O₂ pesa más que menos presión.

## 6. Informe de confianza (lo que nadie más tiene)
`confianza = evidencia × f_combustible × f_gravedad × f_validación` (0-100).
- f_combustible: sólido 1,0 · mezcla con sólido 0,7 · gas/gota/aerosol 0,4 (el modelo se entrenó con sólidos; lo demás es extrapolación).
- f_gravedad: microgravedad 1,0 · parcial emulada 0,6 · parcial pendiente o desconocida 0,4.
- f_validación: 0,85 fijo mientras no haya contraste independiente. **Es un tope honesto**: ninguna investigación pasa de 85.
- Separa las 6 entradas del modelo en **verificado / parcial / inferido / supuesto**, y un **análisis tornado** (cuánto mueve el índice cada variable desconocida): dice qué dato pedirle primero a PSI. Exporta PDF de una página.
- Son heurísticas de diseño explicables, **no probabilidades calibradas**.

## 7. Qué pasa cuando llegan datos nuevos
1. Se leen archivos de PSI (script de ingesta) o un CSV (botón «Datos de prueba», reversible).
2. IGNIS reconoce columnas y unidades (kPa, psi, atm…). Lo que no entiende se ignora y se informa.
3. **Clasificación**: busca palabras clave (p. ej. «cotton», «heptane», «smoke», «extinguish») en nombre, combustible, hardware y objetivos y **sugiere** combustible, familia y áreas. Queda marcada «sugerida» hasta confirmarla; sin pistas, queda «sin clasificar».
4. Entra al ranking, Pareto, mapa y Confianza, marcada como nueva/provisional. Si no declara O₂ o presión, esos campos se infieren del entorno y el punto muestra su intervalo.
5. Si el catálogo falla, se sirve un respaldo y se avisa.

## 8. Límites que hay que decir (y cómo decirlos)
- Modelo sintético calibrado con anclas, **sin validación independiente** (pendiente: contraste con NTRS y revisión de un especialista).
- Sin datos de gravedad parcial: PSI aún no los tiene (LUCI y FM2 los aportarán). El Dashboard lo marca.
- Sin modelo físico de supresión (dilución con CO₂/helio): está en la hoja de ruta; hoy el copiloto usa reglas.
- Marte usa la misma atmósfera que la Luna **como supuesto**.
- Traje espacial (100 % O₂, 29,6 kPa) fuera de dominio: no se evalúa.
- Hardware (Arduino + DHT11) probado solo en simulación; el DHT11 mide aire, no la reacción.
- Docker no se probó.

## 9. Guion de demo (≈ 3 min, pestaña Investigaciones)
1. «Hay decenas de experimentos y es difícil saber cuál importa.» → Ranking para la Luna (Saffire-I primero). 20 s
2. **Pareto**: «No ordeno por un solo criterio: busco riesgo alto con poca evidencia.» Explica frontera y hipervolumen. 40 s
3. **Mapa**: «Donde no hay caja, nadie ha probado.» Mueve a 30 % / 70 kPa. 25 s
4. **Base lunar**: «+X puntos sobre la ISS, y esto es lo verificado y lo supuesto.» 30 s
5. **Confianza**: elige FM2 (baja) y Saffire-I (85): «Dice qué dato pedir primero.» Exporta PDF. 40 s
6. **Datos de prueba**: sube el CSV; aparece clasificada y marcada PRUEBA. 20 s
7. Cierre: Hoja de ruta + «Del espacio a la Tierra». 15 s
Atajo: botón **▶ Demo guiada** (← → cambian de paso, Espacio pausa, Esc sale).

## 10. Preguntas probables
- *¿Está validado?* No con datos independientes; está calibrado con anclas y lo decimos (tope 0,85).
- *¿Por qué no usar IA generativa?* La prioridad es que cada número sea trazable; un puntaje explicable vale más que uno opaco.
- *¿Y si cambia el catálogo?* Todo se recalcula; lo nuevo entra marcado y con la clasificación sugerida.
- *¿Qué es el hipervolumen?* Cuánto riesgo queda sin respaldo; no es seguridad.
