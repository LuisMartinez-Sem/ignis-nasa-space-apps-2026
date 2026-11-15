"""Incidentes históricos: modelos Pydantic y catálogo cargado desde `data/incidents/*.json`.

Principio de diseño: ningún dato histórico va en el código. Cada incidente es un JSON
validado; cada hecho trae su `confianza` y su `fuente`. Lo que no está documentado se
deja SIN hora (`t_s = null`) en lugar de inventarse: un jurado técnico lo verificaría.
"""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.config import RAIZ_PROYECTO
from src.domain import CondicionesHistoricas
from src.senales import TIPOS_EVENTO

logger = logging.getLogger(__name__)

DIRECTORIO_INCIDENTES = RAIZ_PROYECTO / "data" / "incidents"
DIRECTORIO_PROPIOS = RAIZ_PROYECTO / "data" / "incidents_propios"  # incidentes que agrega el investigador (se pueden quitar)
PATRON_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,59}$")

# documentado: figura en la fuente · aproximado: inferido de la fuente · no_verificado:
# solo en fuentes secundarias · ilustrativo: reconstrucción nuestra, NO medida ·
# modelo: lo calcula el pipeline de IGNIS · supuesto: parámetro que fijamos nosotros
Confianza = Literal["documentado", "aproximado", "no_verificado", "ilustrativo", "modelo", "supuesto"]
CategoriaEvento = Literal["contexto", "deteccion", "respuesta", "escalada", "resolucion"]


class ErrorIncidente(ValueError):
    """Incidente inexistente, mal formado o referencias inconsistentes."""


class TipoComparativa(StrEnum):
    """Qué se compara en cada incidente (no todos admiten la misma comparación)."""

    DETECCION_RESPUESTA = "deteccion_respuesta"  # ventana de oportunidad vs reacción de IGNIS
    PRECONDICION = "precondicion"  # IGNIS evalúa el riesgo ANTES de la ignición
    FALSA_ALARMA = "falsa_alarma"  # IGNIS debe NO escalar ante un pico aislado
    VALIDACION = "validacion"  # predicción del modelo vs. medición publicada


class Fuente(BaseModel):
    """Referencia documental verificable."""

    model_config = ConfigDict(extra="forbid")

    id: int
    titulo: str
    organizacion: str
    url: str | None = None
    fiabilidad: Literal["alta", "media", "baja"]
    nota: str = ""


class EventoHumano(BaseModel):
    """Hecho de la cronología real. `t_s = None` => sin hora documentada."""

    model_config = ConfigDict(extra="forbid")

    t_s: float | None
    accion: str
    resultado: str = ""
    categoria: CategoriaEvento
    confianza: Confianza
    fuente: int | None = None


class PuntoTelemetria(BaseModel):
    """Punto clave de la telemetría ILUSTRATIVA; las variables ausentes se interpolan."""

    model_config = ConfigDict(extra="forbid")

    t_s: float = Field(..., ge=0)
    fraccion_o2: float | None = None
    velocidad_flujo_cm_s: float | None = None
    presion_kpa: float | None = None
    temperatura_ambiente_k: float | None = None
    temperatura_reaccion_k: float | None = None


class Medicion(BaseModel):
    """Valor medido y publicado de un experimento."""

    model_config = ConfigDict(extra="forbid")

    velocidad_propagacion_mm_s: float = Field(..., ge=0)
    confianza: Confianza
    fuente: int
    nota: str = ""


class Experimento(BaseModel):
    """Una configuración experimental (p. ej. una muestra de Saffire)."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    condiciones: CondicionesHistoricas
    supuestos: list[str] = Field(default_factory=list)
    medicion: Medicion | None = None
    fuente: int | None = None


class TrazaDetector(BaseModel):
    """Qué traza sintética de sensores representa el evento ante el detector temporal."""

    model_config = ConfigDict(extra="forbid")

    tipo: str
    semilla: int = 0

    @model_validator(mode="after")
    def _tipo_valido(self) -> TrazaDetector:
        if self.tipo not in TIPOS_EVENTO:
            raise ValueError(f"tipo de traza inválido: {self.tipo!r}")
        return self


class Incidente(BaseModel):
    """Incidente histórico completo, listo para simular."""

    model_config = ConfigDict(extra="forbid")

    id: str
    nombre: str
    fecha: str
    fecha_nota: str = ""
    lugar: str
    regimen_gravedad: Literal["microgravedad", "1g"]
    tipo: TipoComparativa
    es_incendio: bool = True
    resumen: str
    modelo_aplicable: bool
    fuera_de_dominio: bool = False  # atmósfera fuera de RANGOS: el HUD no debe esperar un índice
    advertencia_modelo: str | None = None
    duracion_simulacion_s: float = Field(60.0, gt=0, le=3600)
    inicio_evento_s: float = Field(0.0, ge=0)
    traza_detector: TrazaDetector | None = None
    condiciones_base: CondicionesHistoricas | None = None
    telemetria_ilustrativa: list[PuntoTelemetria] = Field(default_factory=list)
    timeline_humano: list[EventoHumano] = Field(default_factory=list)
    ventana_humana_s: tuple[float, float] | None = None
    ventana_nota: str = ""
    experimentos: list[Experimento] = Field(default_factory=list)
    propio: bool = False  # aportado por el usuario: aparece marcado y es el único tipo que se puede quitar
    supuestos_ignis: list[str] = Field(default_factory=list)
    fuentes: list[Fuente]

    @model_validator(mode="after")
    def _coherencia(self) -> Incidente:
        if not PATRON_ID.fullmatch(self.id):
            raise ValueError(f"id inválido: {self.id!r}")
        ids = [f.id for f in self.fuentes]
        if len(ids) != len(set(ids)):
            raise ValueError("ids de fuente duplicados")
        referencias = [e.fuente for e in self.timeline_humano if e.fuente is not None]
        referencias += [x.fuente for x in self.experimentos if x.fuente is not None]
        referencias += [x.medicion.fuente for x in self.experimentos if x.medicion]
        faltantes = sorted(set(referencias) - set(ids))
        if faltantes:
            raise ValueError(f"referencias a fuentes inexistentes: {faltantes}")
        tiempos = [p.t_s for p in self.telemetria_ilustrativa]
        if tiempos != sorted(tiempos):
            raise ValueError("telemetria_ilustrativa debe estar ordenada por t_s")
        if self.ventana_humana_s and self.ventana_humana_s[0] > self.ventana_humana_s[1]:
            raise ValueError("ventana_humana_s debe ser (mínimo, máximo)")
        requisitos = {
            TipoComparativa.DETECCION_RESPUESTA: bool(
                self.condiciones_base and self.telemetria_ilustrativa and self.traza_detector
            ),
            TipoComparativa.PRECONDICION: self.condiciones_base is not None,
            TipoComparativa.FALSA_ALARMA: bool(self.condiciones_base and self.traza_detector),
            TipoComparativa.VALIDACION: bool(self.experimentos),
        }
        if not requisitos[self.tipo]:
            raise ValueError(f"faltan datos requeridos para el tipo '{self.tipo.value}'")
        return self


class ResumenIncidente(BaseModel):
    """Ficha corta para el listado."""

    id: str
    nombre: str
    fecha: str
    lugar: str
    regimen_gravedad: str
    tipo: TipoComparativa
    es_incendio: bool
    modelo_aplicable: bool
    resumen: str
    n_fuentes: int
    propio: bool = False


class CatalogoIncidentes:
    """Carga perezosa y validada de los JSON de un directorio."""

    def __init__(self, directorio: Path = DIRECTORIO_INCIDENTES, directorio_propios: Path | None = None) -> None:
        self.directorio = directorio
        # Por defecto los propios viven junto al catálogo base; con un directorio de pruebas, dentro de él (sin tocar el real)
        self.directorio_propios = directorio_propios if directorio_propios is not None else (DIRECTORIO_PROPIOS if directorio == DIRECTORIO_INCIDENTES else directorio / "propios")
        self._incidentes: dict[str, Incidente] | None = None

    def _cargar(self) -> dict[str, Incidente]:
        if self._incidentes is not None:
            return self._incidentes
        incidentes: dict[str, Incidente] = {}
        if not self.directorio.is_dir():
            logger.warning("No existe el directorio de incidentes", extra={"ruta": str(self.directorio)})
        else:
            archivos = sorted(self.directorio.glob("*.json")) + (sorted(self.directorio_propios.glob("propio-*.json")) if self.directorio_propios.is_dir() else [])
            for archivo in archivos:
                try:
                    incidente = Incidente.model_validate(json.loads(archivo.read_text(encoding="utf-8")))
                except (OSError, ValueError, ValidationError):
                    # Un JSON roto no debe tumbar el catálogo: se omite con traza completa
                    logger.error("Incidente inválido; se omite", extra={"archivo": archivo.name}, exc_info=True)
                    continue
                if incidente.id in incidentes:
                    logger.error("Id de incidente duplicado; se omite", extra={"archivo": archivo.name})
                    continue
                incidentes[incidente.id] = incidente
        self._incidentes = incidentes
        return incidentes

    def listar(self) -> list[ResumenIncidente]:
        """Resumen de todos los incidentes válidos, en orden de id."""
        return [
            ResumenIncidente(
                id=i.id, nombre=i.nombre, fecha=i.fecha, lugar=i.lugar,
                regimen_gravedad=i.regimen_gravedad, tipo=i.tipo, es_incendio=i.es_incendio,
                modelo_aplicable=i.modelo_aplicable, resumen=i.resumen, n_fuentes=len(i.fuentes), propio=i.propio,
            )
            for i in sorted(self._cargar().values(), key=lambda x: x.id)
        ]

    def obtener(self, identificador: str) -> Incidente:
        """Devuelve un incidente.

        Raises:
            ErrorIncidente: si el id es inválido o no existe.
        """
        if not PATRON_ID.fullmatch(identificador):
            raise ErrorIncidente(f"Identificador de incidente inválido: {identificador!r}")
        try:
            return self._cargar()[identificador]
        except KeyError:
            raise ErrorIncidente(f"No existe el incidente '{identificador}'") from None


    def agregar_propio(self, datos: dict) -> Incidente:
        """Valida y guarda un incidente aportado por el investigador. El id siempre empieza por «propio-».

        Raises:
            ErrorIncidente: datos inválidos o id repetido.
        """
        datos = {**datos, "propio": True}
        try:
            incidente = Incidente.model_validate(datos)
        except ValidationError as error:
            raise ErrorIncidente(f"Incidente inválido: {error.errors()[0]['msg']}") from error
        if not incidente.id.startswith("propio-"):
            raise ErrorIncidente("El id de un incidente propio debe empezar por 'propio-'")
        if incidente.id in self._cargar():
            raise ErrorIncidente(f"Ya existe el incidente '{incidente.id}'")
        self.directorio_propios.mkdir(parents=True, exist_ok=True)
        (self.directorio_propios / f"{incidente.id}.json").write_text(incidente.model_dump_json(indent=2), encoding="utf-8")
        self._incidentes = None
        return incidente

    def quitar_propio(self, identificador: str) -> None:
        """Quita un incidente propio. Los incidentes base nunca se pueden quitar.

        Raises:
            ErrorIncidente: id inválido, no propio o inexistente.
        """
        if not PATRON_ID.fullmatch(identificador) or not identificador.startswith("propio-"):
            raise ErrorIncidente("Solo se pueden quitar los incidentes propios (id 'propio-…')")
        archivo = self.directorio_propios / f"{identificador}.json"
        if not archivo.is_file():
            raise ErrorIncidente(f"No existe el incidente propio '{identificador}'")
        archivo.unlink()
        self._incidentes = None
