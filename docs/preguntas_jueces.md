# 20 preguntas anticipadas de los jueces

Regla: respuesta corta primero, límite honesto después. Cifras: `modelos/reporte.json`, `docs/pitch.md`.

**1. ¿Usan datos reales de NASA?**
Aún no. Todo el ML se entrenó con datos sintéticos semi-empíricos y la API lo informa (`origen_datos`). PSI exige registro; el pipeline de ingesta está probado con datos simulados y lo ejecutamos en cuanto lleguen.

**2. Entonces, ¿qué demuestran hoy?**
La mecánica y la latencia: detección multicanal en ~1 ms/muestra, sin falsas alarmas en 600 secuencias sintéticas, explicabilidad y el flujo completo de datos. No demostramos exactitud física.

**3. ¿Qué tan mal está el modelo contra la realidad?**
Sin calibrar era 193 % sobre las dos mediciones de Saffire-I; tras calibrar con ellas es 0,9 %. Es un ajuste, no una validación independiente: esas dos mediciones están en el entrenamiento. La validación contra tablas de NTRS está en curso.

**4. ¿Por qué no han cerrado esa brecha?**
Los CSV de PSI son índices de experimentos y los datos crudos son imágenes que hay que procesar (video → velocidad). No lo hemos hecho; calibramos con valores publicados y dejamos el pipeline listo.

**5. ¿Qué es una llama fría y por qué importa?**
Combustión de baja temperatura (550–800 K) casi sin luz visible. Una cámara común no la ve y puede reavivarse; en pruebas sintéticas la ve solo el 2 % de las veces.

**6. ¿Por qué un TCN y no un LSTM/Transformer/umbral?**
Es causal (sin mirar el futuro), de latencia fija y ~1 ms por muestra en CPU, con campo receptivo conocido. Un umbral de 30 K detecta rápido pero da 8,1 falsas alarmas/h; uno de 60 K no las da pero pierde 16 % de las llamas frías. Detalle en `docs/science.md`.

**7. ¿No está sobreajustado a sus propias señales sintéticas?**
Sí, puede estarlo: el generador y el detector son nuestros. Por eso la cifra solo vale para mecánica/latencia, y la prueba real es con hardware o datos PSI.

**8. ¿Cómo evitan falsas alarmas?**
Consenso multicanal más persistencia (3 votos seguidos con P ≥ 0,60). En el escenario "falsa alarma ISS 2015" un pico en un solo sensor no dispara la alarma.

**9. ¿La falsa alarma de la ISS fue por amoníaco? ¿IGNIS la habría detectado?**
Fue amoníaco y un multiplexor defectuoso: fuera de alcance. Usamos una traza sintética análoga solo para ilustrar la discriminación de picos aislados.

**10. ¿Por qué Apollo 1 no tiene índice de riesgo?**
Ocurrió en 1 g con O₂ al 100 %: fuera del dominio del modelo (O₂ 16–40 %). Evaluarlo sería extrapolar sin base, así que el HUD dice "fuera de dominio".

**11. El índice sale alto con aire normal, ¿no es una falsa alarma permanente?**
El índice mide severidad *si hubiera ignición*. El HUD solo muestra ALERTA/CRÍTICO con evento (ΔT ≥ 50 K o alarma del detector); sin evento muestra NOMINAL y "potencial latente".

**12. ¿De dónde salen los pesos 0,55/0,30/0,15 y la tanh?**
Son una decisión de diseño documentada (propagación pesa más; la tanh satura la velocidad en lugar de cortarla). No están calibrados con datos reales ni validados todavía.

**13. ¿Y el "tiempo antes de propagación"?**
Es distancia ÷ velocidad de llama del modelo, con 10 cm de combustible contiguo como **supuesto** declarado en el mensaje. No es una medición.

**14. ¿Localizan el fuego?**
No. El sector y las coordenadas del HUD son parte del guion de la demo y están rotulados como simulados.

**15. ¿Qué incertidumbre tienen las predicciones?**
El ensemble profundo reporta incertidumbre (±mm/s) y el HUD avisa si RF y profundo divergen. Es incertidumbre del modelo, no de la física.

**16. ¿RF o red profunda?**
Sobre el dataset sintético el profundo tiene mejor R² (0,991 vs 0,946) y MAE (0,18 vs 0,58 mm/s). Con datos reales repetiremos la comparativa (`make psi-reporte VERSION=<id>`); con pocas filas no sobreinterpretaremos.

**17. ¿Qué variables físicas faltan?**
Radiación, geometría real de la cabina, productos de combustión, supresión y otras; están listadas en `GET /api/v1/modelo/variables_no_incluidas`.

**18. ¿Cómo se despliega en una nave real?**
No afirmamos que se pueda hoy. El contrato de sensores (6 canales, 10 Hz) permite sustituir la fuente sintética por hardware; la certificación es otro proceso.

**19. ¿Ha sido revisado por un experto?**
Todavía no: el HUD muestra "Validación pendiente". Hay 5 preguntas y un formulario listos (`docs/validacion_externa.md`).

**20. ¿Qué harían con otra semana?**
Ingestar PSI (BASS/Saffire para propagación; FLEX/CFI para llama fría), reentrenar, recalcular el error de Saffire-I y conseguir un validador.
