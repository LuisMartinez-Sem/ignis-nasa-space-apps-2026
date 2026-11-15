"""Utilidades transversales: logging estructurado (JSON por línea)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

# Atributos estándar de LogRecord; todo lo demás se considera contexto `extra=`.
_ATRIBUTOS_ESTANDAR = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class FormateadorJson(logging.Formatter):
    """Una línea JSON por evento: fácil de filtrar con jq o ingerir en un agregador."""

    def format(self, record: logging.LogRecord) -> str:
        """Serializa el registro, incluyendo campos `extra` y traza de excepción."""
        evento: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        for clave, valor in record.__dict__.items():
            if clave not in _ATRIBUTOS_ESTANDAR and not clave.startswith("_"):
                evento[clave] = valor
        if record.exc_info:
            evento["excepcion"] = self.formatException(record.exc_info)
        # default=str evita que un objeto no serializable tire abajo el logger
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logging(nivel: str = "INFO") -> None:
    """Configura el logger raíz con salida JSON a stdout (idempotente)."""
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for manejador in list(raiz.handlers):
        if getattr(manejador, "_es_ignis", False):
            raiz.removeHandler(manejador)
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(FormateadorJson())
    manejador._es_ignis = True  # type: ignore[attr-defined]
    raiz.addHandler(manejador)
