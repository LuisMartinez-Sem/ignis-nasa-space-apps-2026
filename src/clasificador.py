"""Clasificación SUGERIDA de investigaciones nuevas por palabras clave (combustible, familia y áreas de seguridad).

Cuando entra una investigación que el catálogo no conocía, IGNIS no adivina en silencio: busca palabras clave en el nombre, el
combustible, el hardware y los objetivos, propone una clasificación y la deja marcada como «sugerida» (sigue en
`campos_no_verificados`) hasta que alguien la confirme. Si no hay coincidencias, queda sin clasificar. Es una heurística
transparente, no un modelo de lenguaje: las listas de palabras están aquí para poder auditarlas.
"""

from __future__ import annotations

import re
import unicodedata

COMBUSTIBLE: dict[str, tuple[str, ...]] = {
    "solido": ("pmma", "sibal", "cotton", "algodon", "cellulose", "celulosa", "nomex", "fabric", "tela", "tejido", "paper", "papel", "plastic", "plastico",
               "polymer", "polimero", "solid", "solido", "sample sheet", "fiberglass", "fibra de vidrio", "polyethylene", "polietileno", "kapton", "teflon"),
    "gas": ("propane", "propano", "methane", "metano", "ethylene", "etileno", "gaseous", "gaseoso", "gas fuel", "burner", "quemador", "hydrogen", "hidrogeno", "jet flame", "diffusion flame"),
    "gota": ("droplet", "gota", "heptane", "heptano", "methanol", "metanol", "ethanol", "etanol", "liquid fuel", "combustible liquido", "decane", "decano"),
    "aerosol": ("smoke", "humo", "soot", "hollin", "particle", "particula", "aerosol", "dust", "polvo"),
}
FAMILIA = {"solido": "solidos", "gas": "gases", "gota": "gotas", "aerosol": "humo"}
AREAS: dict[str, tuple[str, ...]] = {
    "supresion": ("extinguish", "extincion", "suppress", "supres", "co2", "carbon dioxide", "dioxido de carbono", "helium", "helio", "water mist", "niebla de agua", "dilution", "dilucion", "agent"),
    "deteccion": ("detect", "deteccion", "alarm", "alarma", "smoke", "humo", "sensor", "aerosol", "dust", "polvo", "particle", "particula"),
    "prevencion": ("flammab", "inflamab", "ignition", "ignicion", "encendido", "flame spread", "propagacion", "limiting oxygen", "oxigeno limite", "material", "fire safety", "seguridad contra incendios"),
}


def _normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def _contiene(texto: str, clave: str) -> bool:
    """Coincidencia por palabra (o prefijo de palabra) para no confundir p. ej. «gas» con «gasto»."""
    return re.search(rf"(?<![a-z0-9]){re.escape(clave)}", texto) is not None


def clasificar(*textos: str) -> dict[str, object]:
    """Devuelve `combustible_tipos`, `familia`, `areas_seguridad` y los motivos (palabras halladas). Listas vacías si no hay pistas."""
    t = _normalizar(" ".join(x for x in textos if x))
    comb, motivos = [], []
    for tipo, claves in COMBUSTIBLE.items():
        hallados = [c for c in claves if _contiene(t, _normalizar(c))]
        if hallados:
            comb.append(tipo)
            motivos.append(f"combustible «{tipo}» por: {', '.join(hallados[:3])}")
    areas = []
    for area, claves in AREAS.items():
        hallados = [c for c in claves if _contiene(t, _normalizar(c))]
        if hallados:
            areas.append(area)
            motivos.append(f"área «{area}» por: {', '.join(hallados[:3])}")
    return {"combustible_tipos": comb, "familia": FAMILIA[comb[0]] if len(comb) == 1 else "otra", "areas_seguridad": areas, "motivos": motivos}
