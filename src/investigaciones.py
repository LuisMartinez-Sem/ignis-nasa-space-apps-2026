"""Dashboard de investigaciones de combustión (reto NASA 2026): catálogo, ranking explicable, huecos y exportación.

Honestidad: el catálogo sale de `data/investigaciones.json` (texto del reto + anclas del equipo); los metadatos reales de PSI
no se han leído. Un campo desconocido es `null` y puntúa neutro, nunca se rellena. El ranking es una HEURÍSTICA de diseño
con pesos explícitos (no validada por expertos) y cada puntaje trae su desglose. Es un SI determinista (reglas), no un LLM.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

RUTA_CATALOGO = Path(__file__).resolve().parent.parent / "data" / "investigaciones.json"
RUTA_ANCLAS = Path(__file__).resolve().parent.parent / "data" / "anclas_reales.json"

Familia = Literal["solidos", "gases", "gotas", "humo", "otra"]
Combustible = Literal["solido", "gas", "gota", "aerosol"]
Area = Literal["prevencion", "deteccion", "supresion"]
Gravedad = Literal["microgravedad", "parcial_emulada", "parcial_pendiente", "desconocida"]
IdEntorno = Literal["iss", "luna", "marte", "traje"]

PESOS = {"o2": 25.0, "presion": 10.0, "combustible": 20.0, "seguridad": 20.0, "datos": 15.0, "gravedad": 10.0}  # suman 100
PUNTAJE_COMBUSTIBLE = {"solido": 1.0, "aerosol": 0.7, "gas": 0.5, "gota": 0.45}  # sólidos = lo que arde en un hábitat
NEUTRO_DESCONOCIDO = 0.4  # un dato desconocido no suma lo mismo que uno verificado


class Rango(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None


class Investigacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    nombre: str
    nombre_completo: str
    familia: Familia
    combustible_tipos: list[Combustible]
    combustible_detalle: str
    hardware: list[str]
    instalacion: str
    objetivos: str
    areas_seguridad: list[Area]
    o2_pct: Rango
    flujo_cm_s: Rango | None = None
    presion_kpa: Rango | None = None
    gravedad: Gravedad
    datos_en_psi: bool | None
    campos_no_verificados: list[str]
    fuente: str
    nota_o2: str | None = None
    nota_presion: str | None = None


class Entorno(BaseModel):
    id: IdEntorno
    nombre: str
    o2_pct: float
    presion_kpa: float
    gravedad_g: float | None
    es_supuesto: bool
    nota: str


ENTORNOS: dict[str, Entorno] = {
    "iss": Entorno(id="iss", nombre="Estación Espacial Internacional", o2_pct=21.0, presion_kpa=101.3, gravedad_g=0.0, es_supuesto=False,
                   nota="Aire normal en microgravedad."),
    "luna": Entorno(id="luna", nombre="Base lunar / rover presurizado", o2_pct=30.0, presion_kpa=70.3, gravedad_g=0.166, es_supuesto=False,
                    nota="Reto: O₂ probablemente ≥ 30 % con presión ≤ 10,2 psi (70,3 kPa); gravedad lunar 1/6 g."),
    "marte": Entorno(id="marte", nombre="Hábitat / rover en Marte", o2_pct=30.0, presion_kpa=70.3, gravedad_g=0.38, es_supuesto=True,
                     nota="SUPUESTO: se asume la misma atmósfera intermedia que la Luna (el reto la agrupa con la Luna); gravedad 0,38 g."),
    "traje": Entorno(id="traje", nombre="Traje espacial", o2_pct=100.0, presion_kpa=29.6, gravedad_g=None, es_supuesto=False,
                     nota="Reto: 100 % O₂ a 4,3 psi (29,6 kPa). Fuera del dominio del modelo de IGNIS."),
}


class Desglose(BaseModel):
    componente: str
    peso: float
    valor: float = Field(..., ge=0, le=1)
    aporte: float
    motivo: str


class InvestigacionRankeada(BaseModel):
    investigacion: Investigacion
    entorno: IdEntorno
    puntaje: float = Field(..., ge=0, le=100)
    posicion: int
    desglose: list[Desglose]
    interpretacion: str
    confianza: Literal["alta", "media", "baja"]  # según cuántos campos del cálculo son desconocidos


class Hueco(BaseModel):
    id: str
    ambito: Literal["nasa_psi", "ignis"]
    severidad: Literal["alta", "media", "baja"]
    titulo: str
    detalle: str
    entornos: list[str]
    fuente: str
    accion_sugerida: str


class ErrorCatalogo(ValueError):
    """Catálogo ausente o inválido (solo la lectura estricta lo lanza)."""


class EstadoCatalogo(BaseModel):
    """De dónde salió el catálogo servido: el sistema nunca se cae, pero siempre dice con qué trabaja."""

    origen: Literal["archivo", "respaldo"]
    detalle: str
    ingesta_aplicada: list[str] = Field(default_factory=list)
    nuevas_ingestadas: list[str] = Field(default_factory=list, description="Investigaciones que NO estaban en el catálogo y entraron por ingesta")
    huella: str = Field("", description="Identifica el contenido servido: si cambia, hay información nueva (el HUD se actualiza solo)")
    prueba: list[str] = Field(default_factory=list, description="Investigaciones afectadas por un CSV de PRUEBA (no son datos de la NASA); vacío = modo normal")


_CACHE: dict[tuple, tuple[list[Investigacion], EstadoCatalogo]] = {}


def leer_catalogo_estricto(ruta: Path) -> list[Investigacion]:
    """Lee y valida el archivo del catálogo.

    Raises:
        ErrorCatalogo: archivo ausente, JSON roto, esquema inválido o ids duplicados.
    """
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        lista = [Investigacion.model_validate(x) for x in crudo["investigaciones"]]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ErrorCatalogo(f"Catálogo de investigaciones inválido: {error}") from error
    ids = [i.id for i in lista]
    if not lista or len(ids) != len(set(ids)):
        raise ErrorCatalogo("catálogo vacío o con ids duplicados")
    return lista


def _catalogo_respaldo() -> list[Investigacion]:
    from src.investigaciones_respaldo import CATALOGO_RESPALDO

    return [Investigacion.model_validate(x) for x in CATALOGO_RESPALDO]


def aplicar_ingesta(lista: list[Investigacion], ruta: Path) -> tuple[list[Investigacion], list[str]]:
    """Aplica las actualizaciones ingestadas de datos reales (`scripts/ingestar_datos_nasa.py`).

    Una ingesta ilegible se ignora (se registra y se sirve el catálogo base): nunca tumba la API.
    """
    if not ruta.exists():
        return lista, []
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        actualizaciones = contenido["actualizaciones"]
        salida = list(lista)
        for crudo in contenido.get("nuevas", []):  # investigaciones que el catálogo no tenía (nombres nuevos de la NASA)
            try:
                nueva_inv = Investigacion.model_validate(crudo)
            except ValueError as error:
                logger.error("Investigación nueva ignorada", extra={"error": str(error)[:200]})
                continue
            if all(i.id != nueva_inv.id for i in salida):
                salida.append(nueva_inv)
        por_id = {i.id: i for i in salida}
        aplicadas: list[str] = []
        for id_, cambios in actualizaciones.items():
            base = por_id.get(id_)
            if base is None:
                continue
            datos = base.model_dump()
            datos.update({k: v for k, v in cambios.items() if k in {"o2_pct", "flujo_cm_s", "presion_kpa", "hardware", "objetivos",
                                                                   "combustible_detalle", "datos_en_psi", "instalacion"}})
            datos["campos_no_verificados"] = [c for c in base.campos_no_verificados if c not in cambios]
            if cambios.get("fuente_ingesta"):
                datos["fuente"] = f"{base.fuente}; ingesta: {cambios['fuente_ingesta']}"
            nueva = Investigacion.model_validate(datos)
            salida[salida.index(base)] = nueva
            aplicadas.append(id_)
        return salida, aplicadas
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        logger.error("Ingesta de investigaciones ignorada", extra={"error": str(error)})
        return lista, []


def _huella(lista: list[Investigacion]) -> str:
    """Hash corto del contenido: cambia si llega cualquier dato nuevo (sirve para actualizar el HUD sin recargar)."""
    crudo = json.dumps([i.model_dump(mode="json") for i in lista], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:12]


def cargar_catalogo_con_estado(ruta: Path | None = None) -> tuple[list[Investigacion], EstadoCatalogo]:
    """Catálogo + su origen. NUNCA lanza: ante un archivo ausente o corrupto sirve el respaldo hardcodeado.

    Se recarga solo cuando cambian el catálogo o la ingesta (fecha de modificación), sin reiniciar el servidor.
    """
    ruta = ruta or RUTA_CATALOGO
    ruta_ingesta = ruta.with_name("investigaciones_ingestadas.json")  # junto al catálogo
    ruta_prueba = ruta.with_name("investigaciones_prueba.json")  # ensayo reversible (src/importacion_prueba.py)

    def _mtime(p: Path) -> int | None:
        try:
            return p.stat().st_mtime_ns
        except OSError:
            return None

    clave = (str(ruta), _mtime(ruta), str(ruta_ingesta), _mtime(ruta_ingesta), str(ruta_prueba), _mtime(ruta_prueba))
    if clave in _CACHE:
        return _CACHE[clave]
    try:
        lista = leer_catalogo_estricto(ruta)
        base_ids = {i.id for i in lista}
        lista, aplicadas = aplicar_ingesta(lista, ruta_ingesta)
        antes_prueba = {i.id for i in lista}
        lista, aplicadas_prueba = aplicar_ingesta(lista, ruta_prueba)
        en_prueba = sorted(set(aplicadas_prueba) | ({i.id for i in lista} - antes_prueba))
        resultado = (lista, EstadoCatalogo(origen="archivo", detalle=str(ruta.name), ingesta_aplicada=aplicadas + aplicadas_prueba,
                                           nuevas_ingestadas=[i.id for i in lista if i.id not in base_ids], huella=_huella(lista), prueba=en_prueba))
    except ErrorCatalogo as error:
        logger.error("Catálogo ilegible: se sirve el respaldo hardcodeado", extra={"error": str(error)})
        respaldo = _catalogo_respaldo()
        resultado = (respaldo, EstadoCatalogo(origen="respaldo", detalle=f"RESPALDO: {error}", huella=_huella(respaldo)))
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[clave] = resultado
    return resultado


def cargar_catalogo_sin_prueba(ruta: Path | None = None) -> list[Investigacion]:
    """Catálogo base + ingesta REAL, sin la superposición de prueba (la importación de prueba se calcula contra esto)."""
    ruta = ruta or RUTA_CATALOGO
    try:
        lista = leer_catalogo_estricto(ruta)
    except ErrorCatalogo:
        lista = _catalogo_respaldo()
    return aplicar_ingesta(lista, ruta.with_name("investigaciones_ingestadas.json"))[0]


def cargar_catalogo(ruta: Path | None = None) -> list[Investigacion]:
    """Catálogo vigente (con respaldo automático)."""
    return cargar_catalogo_con_estado(ruta)[0]


def limpiar_cache() -> None:
    _CACHE.clear()


def obtener(identificador: str) -> Investigacion | None:
    return next((i for i in cargar_catalogo() if i.id == identificador), None)


def _puntaje_o2(inv: Investigacion, env: Entorno) -> tuple[float, str, bool]:
    r = inv.o2_pct
    if r.min is None and r.max is None:
        return NEUTRO_DESCONOCIDO, "O₂ de las pruebas desconocido (no verificado)", True
    if r.min is None:  # solo se conoce el techo
        if env.o2_pct <= (r.max or 0):
            return 0.7, f"cubre hasta {r.max:g} % O₂ (límite inferior desconocido)", True
        return max(0.0, 1 - (env.o2_pct - (r.max or 0)) / 20), f"no llega a {env.o2_pct:g} % O₂ (máx. {r.max:g} %)", True
    lo, hi = r.min, r.max if r.max is not None else r.min
    if lo <= env.o2_pct <= hi:
        return 1.0, f"cubre {env.o2_pct:g} % O₂ ({lo:g}-{hi:g} %)", False
    distancia = lo - env.o2_pct if env.o2_pct < lo else env.o2_pct - hi
    return max(0.0, 1 - distancia / 20), f"O₂ de las pruebas {lo:g}-{hi:g} %, a {distancia:.1f} puntos de {env.o2_pct:g} %", False


def _puntaje_presion(inv: Investigacion, env: Entorno) -> tuple[float, str, bool]:
    r = inv.presion_kpa
    if r is None or (r.min is None and r.max is None):
        return NEUTRO_DESCONOCIDO, "presión de las pruebas desconocida (no verificado)", True
    lo = r.min if r.min is not None else r.max
    hi = r.max if r.max is not None else r.min
    assert lo is not None and hi is not None
    if lo <= env.presion_kpa <= hi:
        return 1.0, f"cubre {env.presion_kpa:g} kPa ({lo:g}-{hi:g} kPa)", False
    distancia = lo - env.presion_kpa if env.presion_kpa < lo else env.presion_kpa - hi
    return max(0.0, 1 - distancia / 50), f"presión de las pruebas {lo:g}-{hi:g} kPa, a {distancia:.1f} kPa de {env.presion_kpa:g} kPa", False


def puntuar(inv: Investigacion, env: Entorno) -> tuple[float, list[Desglose], int]:
    """Puntaje 0-100 con desglose y número de componentes desconocidos."""
    desconocidos = 0
    v_o2, m_o2, d_o2 = _puntaje_o2(inv, env)
    desconocidos += d_o2
    v_p, m_p, d_p = _puntaje_presion(inv, env)
    desconocidos += d_p
    v_comb = max((PUNTAJE_COMBUSTIBLE[c] for c in inv.combustible_tipos), default=NEUTRO_DESCONOCIDO)  # sin tipo declarado: neutro
    v_seg = len(set(inv.areas_seguridad)) / 3
    v_datos = {True: 1.0, None: 0.5, False: 0.0}[inv.datos_en_psi]
    desconocidos += inv.datos_en_psi is None
    g = env.gravedad_g
    if g is None:
        v_g, m_g = 0.5, "entorno sin gravedad definida"
    elif g < 0.05:  # microgravedad
        v_g = {"microgravedad": 1.0, "parcial_emulada": 0.6, "parcial_pendiente": 0.3, "desconocida": NEUTRO_DESCONOCIDO}[inv.gravedad]
        m_g = f"gravedad {inv.gravedad.replace('_', ' ')} frente a microgravedad"
    else:
        v_g = {"microgravedad": 0.4, "parcial_emulada": 0.8, "parcial_pendiente": 1.0, "desconocida": NEUTRO_DESCONOCIDO}[inv.gravedad]
        m_g = f"gravedad {inv.gravedad.replace('_', ' ')} frente a {g:g} g"
    partes = [
        ("o2", v_o2, m_o2),
        ("presion", v_p, m_p),
        ("combustible", v_comb, "combustible " + ("/".join(inv.combustible_tipos) or "no especificado")),
        ("seguridad", v_seg, "cubre " + (", ".join(inv.areas_seguridad) or "ningún área")),
        ("datos", v_datos, {True: "datos en PSI", None: "disponibilidad en PSI no verificada", False: "sin datos en PSI todavía"}[inv.datos_en_psi]),
        ("gravedad", v_g, m_g),
    ]
    desglose = [Desglose(componente=n, peso=PESOS[n], valor=round(v, 3), aporte=round(PESOS[n] * v, 2), motivo=m) for n, v, m in partes]
    return round(sum(d.aporte for d in desglose), 1), desglose, desconocidos


def interpretar(inv: Investigacion, env: Entorno, puntaje: float, desglose: list[Desglose]) -> str:
    """Frase que explica el puntaje (determinista, basada en el desglose)."""
    nivel = "alta" if puntaje >= 65 else "media" if puntaje >= 45 else "baja"
    por_valor = sorted(desglose, key=lambda d: d.valor * d.peso, reverse=True)
    fuertes = [d.motivo for d in por_valor if d.valor >= 0.8][:2]
    debiles = [d.motivo for d in sorted(desglose, key=lambda d: d.valor) if d.valor <= 0.45][:2]
    t = f"Relevancia {nivel} para {env.nombre} ({puntaje:.0f}/100)."
    if fuertes:
        t += " A favor: " + "; ".join(fuertes) + "."
    if debiles:
        t += " Limita: " + "; ".join(debiles) + "."
    if env.es_supuesto:
        t += " (Entorno basado en un supuesto.)"
    return t


def ranking(entorno: str, area: str | None = None, combustible: str | None = None, minimo: float = 0.0, limite: int = 50) -> list[InvestigacionRankeada]:
    """Investigaciones ordenadas por relevancia para el entorno, con filtros opcionales.

    Raises:
        KeyError: entorno desconocido.
    """
    env = ENTORNOS[entorno]
    salida: list[InvestigacionRankeada] = []
    for inv in cargar_catalogo():
        if area and area not in inv.areas_seguridad:
            continue
        if combustible and combustible not in inv.combustible_tipos:
            continue
        p, desglose, desconocidos = puntuar(inv, env)
        if p < minimo:
            continue
        conf = "alta" if desconocidos == 0 else "media" if desconocidos == 1 else "baja"  # desconocidos: O₂, presión, datos en PSI
        salida.append(InvestigacionRankeada(investigacion=inv, entorno=env.id, puntaje=p, posicion=0, desglose=desglose,
                                            interpretacion=interpretar(inv, env, p, desglose), confianza=conf))
    salida.sort(key=lambda r: (-r.puntaje, r.investigacion.id))
    for i, r in enumerate(salida, 1):
        r.posicion = i
    return salida[:limite]


def puntajes_por_entorno(inv: Investigacion) -> dict[str, float]:
    return {e: puntuar(inv, env)[0] for e, env in ENTORNOS.items()}


# ----------------------------------------------------------------------------------------------- huecos
_FUENTE_RETO = "Texto oficial del reto NASA Space Apps 2026"


def huecos() -> list[Hueco]:
    """Qué falta: huecos de la base de la NASA (según el reto y el catálogo) y huecos propios de IGNIS."""
    cat = cargar_catalogo()
    h: list[Hueco] = [
        Hueco(id="sin-gravedad-parcial", ambito="nasa_psi", severidad="alta", entornos=["luna", "marte"], fuente=_FUENTE_RETO,
              titulo="No hay datos de gravedad parcial en PSI",
              detalle="El reto indica que PSI no tiene datos de combustión en gravedad parcial; se esperan de LUCI y FM2. "
                      "E-FIELD solo la emula con campos eléctricos. Microgravedad y 1 g podrían acotar los valores intermedios.",
              accion_sugerida="Tratar cualquier resultado lunar o marciano como extrapolación y acotarlo con microgravedad y 1 g."),
        Hueco(id="datos-crudos-imagenes", ambito="nasa_psi", severidad="media", entornos=["iss", "luna", "marte"], fuente="Revisión de IGNIS de los CSV de PSI",
              titulo="Los CSV de PSI son índices; los datos crudos son imágenes",
              detalle="Obtener velocidades de propagación exige procesar video/imágenes (seguimiento del frente de llama). Sin eso, un dashboard solo resume metadatos.",
              accion_sugerida="Procesar una muestra de video con seguimiento del frente y publicar las velocidades extraídas."),
        Hueco(id="cohete-fuera-de-alcance", ambito="nasa_psi", severidad="baja", entornos=[], fuente=_FUENTE_RETO,
              titulo="Incendios de cohetes y propelentes fuera de alcance",
              detalle="La combustión en motores de cohete es independiente de la gravedad y PSI no la cubre.", accion_sugerida="No usar PSI para ese caso."),
        Hueco(id="sin-modelo-supresion", ambito="ignis", severidad="alta", entornos=["iss", "luna", "marte"], fuente="Estado de IGNIS",
              titulo="IGNIS no modela la supresión",
              detalle="El reto cubre prevención, detección y supresión (FLEX: dilución con CO₂ y helio). IGNIS predice propagación y detecta; "
                      "solo sugiere acciones por reglas, no cuantifica el efecto de los agentes.",
              accion_sugerida="Añadir un módulo de dilución con datos de FLEX."),
        Hueco(id="traje-fuera-de-dominio", ambito="ignis", severidad="media", entornos=["traje"], fuente="Dominio operativo de IGNIS (O₂ 16-40 %, 35-101,3 kPa)",
              titulo="El modelo no cubre la atmósfera del traje (100 % O₂, 29,6 kPa)",
              detalle="Está fuera del dominio de entrenamiento; IGNIS no la evalúa.", accion_sugerida="Ampliar el dominio con datos de CFI-G (hasta 85 % O₂) solo tras validar."),
        Hueco(id="sin-validacion-externa", ambito="ignis", severidad="alta", entornos=["iss", "luna", "marte"], fuente="Estado de IGNIS",
              titulo="Modelo calibrado, no validado con datos independientes",
              detalle="El dataset es sintético calibrado con 3 anclas publicadas (no verificadas por IGNIS); el 0,9 % de error en Saffire-I es un ajuste.",
              accion_sugerida="Validar contra tablas del NTRS y con revisión de un físico."),
    ]
    for e in ("luna", "marte", "traje"):
        env = ENTORNOS[e]
        cubre = [i for i in cat if "solido" in i.combustible_tipos and i.datos_en_psi and _puntaje_o2(i, env)[0] >= 0.9 and not _puntaje_o2(i, env)[2]]
        if not cubre:
            h.append(Hueco(id=f"sin-solidos-{e}", ambito="nasa_psi", severidad="alta" if e != "traje" else "media", entornos=[e], fuente="Catálogo de IGNIS",
                           titulo=f"Ninguna investigación de sólidos con datos en PSI y O₂ verificado cubre {env.nombre}",
                           detalle=f"Se buscó una investigación con combustible sólido, datos en PSI y rango de O₂ conocido que incluya {env.o2_pct:g} %. "
                                   "Resultado negativo en el catálogo; puede deberse a metadatos aún sin verificar.",
                           accion_sugerida="Leer los metadatos reales de PSI para confirmar el O₂ de BASS, BASS-II y Saffire."))
    return h


# --------------------------------------------------------------------------------- comparación y exportación
def comparar(ids: list[str]) -> dict[str, object]:
    """Matriz de similitudes y diferencias entre investigaciones.

    Raises:
        KeyError: id desconocido.
    """
    invs = []
    for i in ids:
        x = obtener(i)
        if x is None:
            raise KeyError(i)
        invs.append(x)
    campos = {"familia": lambda x: x.familia, "combustible": lambda x: "/".join(x.combustible_tipos), "hardware": lambda x: ", ".join(x.hardware) or "n/d",
              "instalacion": lambda x: x.instalacion, "areas_seguridad": lambda x: ", ".join(x.areas_seguridad), "gravedad": lambda x: x.gravedad,
              "o2_pct": lambda x: "desconocido" if x.o2_pct.min is None and x.o2_pct.max is None else f"{x.o2_pct.min}-{x.o2_pct.max}",
              "datos_en_psi": lambda x: {True: "sí", False: "no", None: "no verificado"}[x.datos_en_psi]}
    filas = [{"campo": c, "valores": {x.id: f(x) for x in invs}, "iguales": len({f(x) for x in invs}) == 1} for c, f in campos.items()]
    return {"ids": ids, "filas": filas, "similitudes": [f["campo"] for f in filas if f["iguales"]], "diferencias": [f["campo"] for f in filas if not f["iguales"]]}


def _seguro_csv(valor: object) -> object:
    """Evita inyección de fórmulas al abrir el CSV en una hoja de cálculo."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def filas_exportacion(conjunto: str = "investigaciones") -> list[dict[str, object]]:
    """Datos estructurados para modelado predictivo."""
    if conjunto == "anclas":
        try:
            anclas = json.loads(RUTA_ANCLAS.read_text(encoding="utf-8"))["anclas"]
            return [{"id": a["id"], "valor": json.dumps(a.get("valor")), "uso": a.get("uso"), "verificacion": a.get("verificacion"),
                     "fuente_indicada": a.get("fuente_indicada"), "condiciones": json.dumps(a.get("condiciones"), ensure_ascii=False)} for a in anclas]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            logger.error("Anclas ilegibles: se exporta el respaldo", extra={"error": str(error)})
            from src.investigaciones_respaldo import ANCLAS_RESPALDO

            return [dict(a) for a in ANCLAS_RESPALDO]
    filas = []
    for inv in cargar_catalogo():
        punt = puntajes_por_entorno(inv)
        filas.append({
            "id": inv.id, "nombre": inv.nombre, "familia": inv.familia, "combustible": "|".join(inv.combustible_tipos),
            "hardware": "|".join(inv.hardware), "areas_seguridad": "|".join(inv.areas_seguridad),
            "o2_pct_min": inv.o2_pct.min, "o2_pct_max": inv.o2_pct.max,
            "presion_kpa_min": inv.presion_kpa.min if inv.presion_kpa else None, "presion_kpa_max": inv.presion_kpa.max if inv.presion_kpa else None,
            "flujo_cm_s_min": inv.flujo_cm_s.min if inv.flujo_cm_s else None, "flujo_cm_s_max": inv.flujo_cm_s.max if inv.flujo_cm_s else None,
            "gravedad": inv.gravedad, "datos_en_psi": inv.datos_en_psi,
            **{f"relevancia_{e}": v for e, v in punt.items()},
            "campos_no_verificados": "|".join(inv.campos_no_verificados), "fuente": inv.fuente,
        })
    return filas


def exportar_csv(conjunto: str = "investigaciones") -> str:
    filas = filas_exportacion(conjunto)
    buf = io.StringIO()
    escritor = csv.DictWriter(buf, fieldnames=list(filas[0]) if filas else ["vacio"])
    escritor.writeheader()
    for f in filas:
        escritor.writerow({k: _seguro_csv(v) for k, v in f.items()})
    return buf.getvalue()


APLICACIONES_TERRESTRES = [
    {"id": "agua-nebulizada", "tecnologia": "Extintores de agua nebulizada (fine water mist)", "origen": "Desarrollados para la ISS", "uso_en_tierra": "Extinción con poca agua en edificios y vehículos.",
     "area": "supresion", "por_que": "Sin gravedad la llama no tiene flotabilidad ni convección: es el laboratorio más limpio para ver cómo el agua fina apaga una llama. Lo aprendido se aplica también en 1 g."},
    {"id": "deteccion-humo", "tecnologia": "Detección de humo", "origen": "Tecnología NASA de detección", "uso_en_tierra": "Mejoras en detectores de humo terrestres.",
     "area": "deteccion", "por_que": "En microgravedad el humo no sube: entender cómo se forma y se mueve sin gravedad ayuda a diseñar detectores que no dependan de la convección."},
    {"id": "equipo-bomberos", "tecnologia": "Equipo de bomberos", "origen": "Tecnología NASA", "uso_en_tierra": "Ropa de protección y tanques de aire.",
     "area": "prevencion", "por_que": "Conocer a qué atmósferas y materiales se enciende un material (prevención) informa qué ropa y qué materiales resisten mejor."},
]
APLICACIONES_AVISO = ("Origen y uso en la Tierra: texto del reto NASA 2026. La relación con cada área de seguridad y el «por qué» son criterio del equipo "
                      "(no una afirmación de la NASA).")
