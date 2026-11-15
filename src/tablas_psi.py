"""Lector TOLERANTE de las tablas experimentales del PSI (PSI-xx_Experimental_table_*.csv).

Las tablas reales de la NASA no traen una columna «investigación»: se identifican por el número PSI del nombre del archivo, mezclan
unidades (atm, bar, mmHg, fracción, %), guardan números como texto («~ 21.5», «20 cm/s», «22.1 to 22.0», «0.5; 1.0; or 3.0»), traen
filas vacías, notas al pie, filas duplicadas, caracteres ilegibles y erratas de fecha. Este módulo las lee sin romperse, extrae SOLO lo
inequívoco (O₂, presión, flujo de aire) y devuelve un informe de calidad en español para el investigador. Lo ambiguo se omite y se dice.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PSI_KPA_ATM, PSI_KPA_BAR, KPA_MMHG = 101.325, 100.0, 0.133322368
DOMINIO = {"o2": (5.0, 100.0), "presion": (1.0, 1000.0), "flujo": (0.0, 1000.0)}  # % · kPa · cm/s: fuera de aquí = dato sospechoso
UNIDADES = {"pct": 1.0, "frac": 100.0, "atm": PSI_KPA_ATM, "bar": PSI_KPA_BAR, "mmhg": KPA_MMHG, "kpa": 1.0, "cm_s": 1.0}
NUM = re.compile(r"\d+(?:\.\d+)?")

# número PSI → adaptador: id del catálogo, nombre y, por campo, (regex de columna, unidad). Solo columnas cuyo significado es inequívoco.
ADAPTADORES: dict[int, dict[str, Any]] = {
    98: {"id": "saffire-i", "nombre": "Saffire-I", "o2": (r"^percent o2", "pct"), "flujo": (r"^air flow", "cm_s")},
    99: {"id": "saffire-ii", "nombre": "Saffire-II", "o2": (r"^percent o2", "pct"), "flujo": (r"^air flow", "cm_s")},
    100: {"id": "saffire-iii", "nombre": "Saffire-III", "flujo": (r"^air flow", "cm_s")},
    159: {"id": "acme-cfi-g", "nombre": "ACME CFI-G", "o2": (r"^xo2( before test)?$", "frac"), "presion": (r"^approx p", "bar")},
    23: {"id": "acme-s-flame", "nombre": "ACME s-Flame", "o2": (r"^atmosphere", "texto%"), "presion": (r"^notes$", "atm_nota"), "combustible": r"^fuel bottle"},
    25: {"id": "bass-ii", "nombre": "BASS-II", "o2": (r"^calibrated initial o2", "pct"), "fechas": r"^date$"},
    26: {"id": "bass", "nombre": "BASS", "fechas": r"^date$", "inventario": True},
    39: {"id": "cfi", "nombre": "CFI", "o2": (r"^oxygen$", "frac"), "presion": (r"^pressure$", "atm"), "combustible": r"^fuel"},
    68: {"id": "flex-2", "nombre": "FLEX-2", "o2": (r"^oxygen mole fraction", "frac"), "presion": (r"^ambient pressure \(atm\)", "atm"),
         "flujo": (r"^flow velocity", "cm_s"), "combustible": r"^sample"},
    69: {"id": "flex", "nombre": "FLEX", "o2": (r"^o initial ambient composition", "frac"), "presion": (r"^ambient pressure; mmhg", "mmhg"),
         "combustible": r"^fuel$", "identificador": r"^flex identifier"},
}


def numero_psi(nombre_archivo: str) -> int | None:
    m = re.match(r"PSI[-_ ]?(\d+)", nombre_archivo, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _decodificar(crudo: bytes) -> tuple[str, str]:
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return crudo.decode(cod), cod
        except UnicodeDecodeError:
            continue
    return crudo.decode("cp1252", errors="replace"), "cp1252 (con bytes inválidos)"


def leer_tolerante(ruta: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Filas de datos limpias + conteos de lo descartado. No lanza por filas vacías, duplicadas ni caracteres ilegibles."""
    texto, cod = _decodificar(ruta.read_bytes())
    filas_crudas = list(csv.reader(io.StringIO(texto)))
    if not filas_crudas:
        raise ValueError("archivo vacío")
    cab = [" ".join(c.split()) for c in filas_crudas[0]]
    info = {"codificacion": cod, "filas_en_archivo": len(filas_crudas) - 1, "filas_vacias": 0, "filas_nota": 0, "filas_duplicadas": 0, "celdas_ilegibles": 0}
    filas, vistas = [], set()
    for r in filas_crudas[1:]:
        celdas = [c.strip() for c in r]
        llenas = [c for c in celdas if c]
        if not llenas:
            info["filas_vacias"] += 1; continue
        if len(llenas) <= 2 and (celdas[0].lower().startswith("note") or len(llenas) < max(3, len(cab) // 4)):
            info["filas_nota"] += 1; continue  # notas al pie y filas de «datos de visualización» sin medidas
        clave = tuple(celdas)
        if clave in vistas:
            info["filas_duplicadas"] += 1; continue
        vistas.add(clave)
        fila = {}
        for k, v in zip(cab, celdas + [""] * (len(cab) - len(celdas))):
            if "�" in v:
                info["celdas_ilegibles"] += 1; v = ""
            fila[k] = v
        filas.append(fila)
    info["filas_utiles"] = len(filas)
    return filas, info


def _columna(filas: list[dict[str, str]], patron: str) -> str | None:
    return next((c for c in filas[0] if re.search(patron, c.lower().replace(" ", " "))), None) if filas else None


def _valores(filas: list[dict[str, str]], col: str, unidad: str, campo: str, descartados: list[str]) -> list[float]:
    lo, hi = DOMINIO[campo]
    salida: list[float] = []
    for f in filas:
        t = f.get(col, "")
        if unidad == "texto%":
            nums = re.findall(r"(\d+(?:\.\d+)?)\s*%", t); fac = 1.0
        elif unidad == "atm_nota":
            nums = re.findall(r"(\d+(?:\.\d+)?)\s*atm", t); fac = PSI_KPA_ATM
        else:
            nums = NUM.findall(t); fac = UNIDADES[unidad]
        for n in nums:
            v = float(n) * fac
            if lo <= v <= hi:
                salida.append(v)
            elif v == 0 and campo == "presion":
                descartados.append(f"presión 0 en «{t}» (valor imposible; se descarta)")
            else:
                descartados.append(f"{campo} {v:.3g} fuera del rango físico razonable ({lo:g}–{hi:g}); se descarta")
    return salida


def _revisar_fechas(filas: list[dict[str, str]], col: str) -> list[str]:
    malas = []
    for f in filas:
        t = f.get(col, "")
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                d = datetime.strptime(t, fmt)
                if not 2000 <= d.year <= datetime.now().year:
                    malas.append(f"fecha «{t}» con año {d.year} (probable errata en la tabla fuente)")
                break
            except ValueError:
                continue
        else:
            if t:
                malas.append(f"fecha «{t}» ilegible (probable errata en la tabla fuente)")
    return malas


def extraer(ruta: Path) -> dict[str, Any]:
    """Extrae de una tabla PSI: rangos de O₂ (%), presión (kPa) y flujo (cm/s) + informe de calidad. Lanza ValueError si no hay adaptador."""
    n = numero_psi(ruta.name)
    if n is None or n not in ADAPTADORES:
        raise ValueError(f"tabla PSI sin adaptador conocido ({ruta.name}): se omite en vez de adivinar columnas")
    ad = ADAPTADORES[n]
    filas, cal = leer_tolerante(ruta)
    avisos: list[dict[str, str]] = []
    descartados: list[str] = []
    res: dict[str, Any] = {"psi": n, "id": ad["id"], "nombre": ad["nombre"], "o2": [], "flujo": [], "presion": [], "combustible_detalle": None, "hardware": set()}
    for campo in ("o2", "presion", "flujo"):
        if campo not in ad:
            continue
        patron, unidad = ad[campo]
        col = _columna(filas, patron)
        if col is None:
            avisos.append({"nivel": "atencion", "texto": f"No se encontró la columna de {campo} (esperada «{patron}»); el formato de la tabla pudo cambiar."}); continue
        res[campo] = _valores(filas, col, unidad, campo, descartados)
        if unidad == "atm_nota" and res[campo]:
            avisos.append({"nivel": "info", "texto": "La presión (~1 atm) viene de una NOTA de la tabla («Atmosphere is ~1 atm…»), no de una columna medida: es aproximada."})
        if not res[campo]:
            avisos.append({"nivel": "info", "texto": f"La columna «{col}» no trae valores de {campo} utilizables."})
    if "combustible" in ad and (c := _columna(filas, ad["combustible"])):
        vistos = list(dict.fromkeys(f[c] for f in filas if f.get(c)))
        res["combustible_detalle"] = "; ".join(vistos)[:300] or None
    if "fechas" in ad and (c := _columna(filas, ad["fechas"])):
        for m in _revisar_fechas(filas, c):
            avisos.append({"nivel": "atencion", "texto": m})
    if "identificador" in ad and (c := _columna(filas, ad["identificador"])):
        por_id: dict[str, int] = {}
        for f in filas:
            por_id[f[c]] = por_id.get(f[c], 0) + 1
        repetidos = sorted(k for k, v in por_id.items() if k and v > 1)
        if repetidos:
            avisos.append({"nivel": "atencion", "texto": f"Identificadores repetidos con valores distintos: {', '.join(repetidos[:5])}. Se conservan ambas filas; conviene revisarlas."})
    if ad.get("inventario"):
        avisos.append({"nivel": "info", "texto": f"Tabla de inventario: lista {len(filas)} ensayos y materiales, pero no trae O₂, presión ni flujo; solo confirma que hay datos en PSI."})
    if n == 25:
        avisos.append({"nivel": "info", "texto": "«Fan display» y «Air display» son lecturas del instrumento (no cm/s); el flujo NO se infiere. Se usa solo el O₂ inicial calibrado."})
        col = _columna(filas, r"^calibrated final o2")
        if col:
            for f in filas:
                try:
                    if float(f[col]) < 5 or float(f[col]) > 25:
                        descartados.append(f"O₂ final {f[col]} % en {f.get('Test #', '?')} (posible error de captura; no se usa)")
                except ValueError:
                    pass
    if cal["filas_vacias"]:
        avisos.append({"nivel": "info", "texto": f"{cal['filas_vacias']} filas vacías ignoradas (la tabla declara más filas de las que tiene datos)."})
    if cal["filas_duplicadas"]:
        avisos.append({"nivel": "atencion", "texto": f"{cal['filas_duplicadas']} filas duplicadas exactas ignoradas (no se cuentan dos veces)."})
    if cal["celdas_ilegibles"]:
        avisos.append({"nivel": "atencion", "texto": f"{cal['celdas_ilegibles']} celdas con caracteres ilegibles (archivo no UTF-8); se tratan como «sin dato»."})
    if cal["filas_nota"]:
        avisos.append({"nivel": "info", "texto": f"{cal['filas_nota']} filas de notas o de datos sin medidas separadas de los ensayos."})
    for d in dict.fromkeys(descartados):
        avisos.append({"nivel": "atencion", "texto": f"Dato descartado: {d}."})
    res["calidad"] = {"archivo": ruta.name, "psi": n, "investigacion": ad["nombre"], **cal, "avisos": avisos,
                      "rangos": {c: [round(min(res[c]), 3), round(max(res[c]), 3)] for c in ("o2", "presion", "flujo") if res[c]}}
    return res


def fusionar_rango(actual: Any, nuevo: dict[str, float]) -> tuple[dict[str, float] | None, str | None]:
    """Rellena el hueco de un rango del catálogo SIN pisar lo conocido. Devuelve (rango a aplicar | None, conflicto | None).

    Conflicto = el archivo se sale de un límite que el catálogo ya conoce (un subconjunto del rango conocido no es conflicto)."""
    if actual is None or (actual.min is None and actual.max is None):
        return dict(nuevo), None
    aviso = None
    if (actual.min is not None and nuevo["min"] < actual.min) or (actual.max is not None and nuevo["max"] > actual.max):
        aviso = f"catálogo {actual.min}-{actual.max} vs archivo {nuevo['min']}-{nuevo['max']} (se conserva lo conocido)"
    if actual.min is not None and actual.max is not None:
        return None, aviso
    return {"min": actual.min if actual.min is not None else nuevo["min"], "max": actual.max if actual.max is not None else nuevo["max"]}, aviso


def unir_rangos(a: dict[str, float] | None, b: dict[str, float] | None) -> dict[str, float] | None:
    """Unión de dos rangos (varias tablas de una misma investigación, p. ej. llamas normales e inversas)."""
    if not a or not b:
        return a or b
    return {"min": min(a["min"], b["min"]), "max": max(a["max"], b["max"])}
