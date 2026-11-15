"""Contratos HTTP/WebSocket. Los modelos de dominio se reutilizan, no se duplican."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.domain import CondicionesAmbiente, ResultadoEvaluacion
from src.model import MetricasEntrenamiento

# Límite de lote: acota CPU y memoria por petición (anti abuso)
MAX_CONDICIONES_POR_LOTE = 500


class SolicitudLote(BaseModel):
    """Varias condiciones evaluadas en una sola pasada vectorizada."""

    model_config = ConfigDict(extra="forbid")

    condiciones: list[CondicionesAmbiente] = Field(
        ..., min_length=1, max_length=MAX_CONDICIONES_POR_LOTE
    )


class RespuestaLote(BaseModel):
    """Resultados en el mismo orden que las condiciones de entrada."""

    resultados: list[ResultadoEvaluacion]


class InfoModelo(BaseModel):
    """Metadatos del modelo en servicio, para auditoría desde el HUD."""

    version: str
    origen_datos: str
    metricas: MetricasEntrenamiento | None


class EstadoSalud(BaseModel):
    """Respuesta de `/health`."""

    estado: str
    modelo_cargado: bool
    version: str = ""
    componentes: dict[str, str] = Field(default_factory=dict)
    motores: list[str] = Field(default_factory=list)
    incidentes: int = 0


class MensajeTelemetria(BaseModel):
    """Mensaje WebSocket servidor→cliente con una evaluación."""

    tipo: str = "telemetria"
    origen: str
    t_s: float | None = None
    condiciones: CondicionesAmbiente
    evaluacion: ResultadoEvaluacion
