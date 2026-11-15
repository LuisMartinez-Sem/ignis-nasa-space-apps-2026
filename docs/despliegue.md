# Despliegue — día del evento

Cristobal: sigue estos pasos en orden. Requisitos: Python 3.11+ (probado en 3.13) y un navegador moderno (Chrome/Edge/Firefox).

## Antes del evento (hacerlo UNA vez, con internet)
1. Descomprime `ignis_FINAL.zip` → se crea la carpeta `ignis/`.
2. Abre una terminal dentro de `ignis/`.
3. Crea el entorno virtual e instala dependencias:
   - Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   - Windows (PowerShell): `python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt`
4. Prueba: `python -m pytest -q` (todo en verde).

## 1. Activar el venv (cada vez)
- Linux/macOS: `cd ignis && source .venv/bin/activate`
- Windows (PowerShell): `cd ignis; .venv\Scripts\Activate.ps1` (en CMD: `.venv\Scripts\activate.bat`)
- Se ve `(.venv)` al inicio del prompt.

## 2. Correr el servidor
`uvicorn api.main:app --host 127.0.0.1 --port 8000`
- Espera el mensaje `Application startup complete`. Si no existe el modelo guardado, entrena al arrancar (tarda); el modelo profundo y el detector cargan en segundo plano unos segundos más.
- Verificación rápida: `curl http://127.0.0.1:8000/api/v1/emergencias` → 3 emergencias (mir-1997, iss-2015, columbus-cool-flame).

## 3. Abrir el HUD
- Navegador: <http://127.0.0.1:8000>
- API interactiva: <http://127.0.0.1:8000/docs>
- Pantalla completa con F11. Sonido apagado por defecto: actívalo con su botón (requiere un clic).

## Si algo falla
- Puerto ocupado: usa `--port 8001` y abre `http://127.0.0.1:8001`.
- HUD en blanco: recarga con Ctrl+F5 y revisa que la terminal siga mostrando el servidor activo.
- Copiloto o escenarios sin respuesta: espera ~30 s a que carguen los modelos.
- Los módulos `frontend/js/{bundle,reconstruccion,whatif}.js` pueden ser placeholders si no se integraron los reales; el HUD base funciona igual.

Límites a decir si preguntan: datos sintéticos calibrados con anclas publicadas (ajuste, no validación); localización 3D no implementada; las fuentes NTRS/PSI/FLEX no fueron verificadas por IGNIS.

## Datos nuevos de la NASA
1. Copiar los CSV/JSON a `data/raw/` y ejecutar `python scripts/ingestar_datos_nasa.py` (`--estricto` falla ante errores; `--forzar` reprocesa).
2. Revisar el reporte en `data/processed/`: los conflictos con valores conocidos no se sobrescriben.
3. Tras editar `data/investigaciones.json`, ejecutar `python scripts/regenerar_respaldo.py`.
