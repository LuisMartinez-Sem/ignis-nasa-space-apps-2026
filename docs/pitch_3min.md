# Pitch de 3 minutos (70 % solución · 30 % límites)

Cifras marcadas con ⓘ salen de `docs/pitch.md`, `modelos/reporte.json` o del comando indicado; no las cambies a mano.

## 0:00–0:25 · El problema (gancho)
Un incendio en una nave no se apaga con agua ni se ventila hacia afuera. En 1997 el fuego de Mir bloqueó una de las dos
cápsulas Soyuz. Y en microgravedad existe algo peor: la **llama fría**, 550–800 K, sin luz visible.

## 0:25–2:05 · La solución (70 %)
1. **Detecta** (0:25–0:55). Un detector temporal (TCN causal) lee 6 sensores a 10 Hz. ⓘ Detección global 100 %, 0 falsas
   alarmas/h, llama fría en 0,7 s (mediana) contra 14,5 s de una cámara visible, que solo ve el 2 % de las llamas frías. Inferencia ≈ 1 ms por muestra.
2. **Explica** (0:55–1:20). El copiloto dice el factor dominante y la acción: "+X pts por cada +1 % de O₂ → ventilar sector".
   Mensajes con formato fijo: crítico, factor dominante, llama fría, extrapolación.
3. **Se ve** (1:20–1:45). Gemelo 3D con visión IR/visible: botón *¿Qué ve el astronauta?* — la llama fría desaparece de la cámara visible.
4. **Se prueba** (1:45–2:05). Reproducción de escenarios e incidentes (Mir, ISS 2015, Apollo 1, Saffire) a 0.5×–10×, con
   latencia sensor → TCN → copiloto medida, y "qué pasaría si" moviendo O₂, flujo y temperatura.

## 2:05–2:50 · Los límites, de frente (30 %)
- Todo el ML se entrenó con **datos sintéticos**. ⓘ Sin calibrar, el error en Saffire-I era 193 %; tras calibrar con las anclas publicadas es 0,9 %. Eso es un **ajuste**, no una validación: las anclas están en el entrenamiento.
- Los CSV de PSI son índices y los datos crudos son imágenes que requieren procesamiento; el pipeline (lectura CSV/HDF5/JSON, unidades, cobertura, versionado con SHA-256) está probado
  con datos simulados. ⓘ La línea final del pitch (filas de Saffire/FLEX/BASS y error reducido) la genera `make psi-reporte`.
- Dominio operativo O₂ 16–40 %, P 35–101 kPa; Apollo 1 (O₂ 100 %) queda **fuera de dominio** y no se evalúa.
- La ubicación del foco en la demo es simulada. La validación externa por un físico/ingeniero sigue **pendiente** (badge visible en el HUD).

## 2:50–3:00 · Cierre
"Esperamos los datos: ingestar, versionar, reentrenar y comparar con un comando. Lo que ven hoy es honesto; lo que sigue es físico real."
