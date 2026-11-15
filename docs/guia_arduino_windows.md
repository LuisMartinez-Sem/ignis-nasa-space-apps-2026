# Puente Arduino UNO R3 + DHT11 en Windows (COM4)

**Qué mide y qué no.** El DHT11 mide temperatura del **aire** (0–50 °C, ±2 °C) y humedad. No detecta llamas. IGNIS usa esa temperatura como `temperatura_ambiente_k`; O₂ (0.21), presión (101.3 kPa) y flujo (10 cm/s) son **valores declarados**, no medidos. El índice resultante es el potencial del entorno según un modelo sintético no validado; no es una alarma de incendio.

## 1. Cableado y sketch
DHT11 → 5 V, GND y señal al pin 2 (supuesto del sketch de ejemplo `arduino/ignis_dht11.ino`; si usa otro pin, cámbielo). Si su sketch ya imprime «Humedad: 45.00 %  Temperatura: 24.00 *C», sirve: el puente toma el número que sigue a «Temperatura». Con `45.0,24.0` (sin etiquetas) añada `--columna 2`.
Cierre el **Monitor Serie** del IDE: solo un programa puede abrir COM4.

## 2. Comandos exactos (PowerShell)
Terminal 1 — servidor (desde la carpeta del proyecto):
```powershell
cd C:\ruta\a\ignis
py -m pip install -r requirements.txt
py -m uvicorn api.main:app --port 8000
```
Espere «Application startup complete».

Terminal 2 — puente:
```powershell
cd C:\ruta\a\ignis
py -m pip install -r requirements-hardware.txt
py hardware_bridge.py --puerto COM4 --baudios 9600 --unidad c --campo ambiente
```
Salida esperada cada ~0.5 s como máximo:
```
[12:01:05] sensor=24 C → índice=65.98 nivel=ALERTA propaga=0.948 llama_fría=INACTIVA
```
Sin Arduino (prueba): `"24.5" | py hardware_bridge.py --stdin`. Respuesta JSON completa: añada `--detallado`. Salir: Ctrl+C.
Si `py` no existe, use `python`. Con Docker: el puente corre en Windows (no en el contenedor) y apunta a `http://127.0.0.1:8000`.

## 3. Si algo falla
| Síntoma | Causa y solución |
|---|---|
| `Puerto COM4 no disponible (… Acceso denegado)` | Monitor Serie u otro programa lo tiene abierto; ciérrelo. El puente reintenta cada 2 s |
| `could not open port 'COM4'` | Número de puerto distinto: Administrador de dispositivos → Puertos (COM y LPT) |
| `Sin datos de COM4 hace 10 s` | Baudios distintos (el sketch debe usar 9600), sketch equivocado o DHT11 colgado |
| `[AVISO] N línea(s) sin temperatura utilizable` | El Arduino envía basura o texto sin número (`ERROR lectura DHT11`, baudios mal); el puente sigue |
| `[ERROR] … fuera del rango` | Unidad mal puesta (`--unidad k` o `f`) o sensor desconectado (lectura absurda) |
| `[ERROR] … Connection refused` | El servidor no está corriendo (Terminal 1) |
| Se desconecta el cable | Mensaje de error, reintentos y «RECONECTADO a COM4» al volver; no hay que reiniciar |
| Letras raras en consola | Se sustituyen automáticamente; no detienen el puente |

## 4. Validación del esquema
El puente envía exactamente: `fraccion_o2`, `velocidad_flujo_cm_s`, `presion_kpa`, `temperatura_ambiente_k`, `espesor_combustible_mm`, `material`, `regimen_flujo` (y `temperatura_reaccion_k` solo con `--campo reaccion`). Un test lo envía a `POST /api/v1/predict` real con el DHT11 en su rango completo (0 y 50 °C) y con un termopar (450 °C): responde 200 en todos los casos (`tests/test_hardware_bridge.py`).
