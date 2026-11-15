"""Configuración externalizada (.env + pydantic-settings). Nada hardcodeado."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del repo: las rutas relativas del .env se resuelven contra ella,
# así el servidor funciona igual lanzado desde cualquier directorio.
RAIZ_PROYECTO: Path = Path(__file__).resolve().parents[1]


class Configuracion(BaseSettings):
    """Parámetros de ejecución de IGNIS, leídos de variables `IGNIS_*`."""

    model_config = SettingsConfigDict(
        env_prefix="IGNIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    entorno: Literal["desarrollo", "pruebas", "produccion"] = "desarrollo"
    nivel_log: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    origenes_cors: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]

    # --- Rutas (relativas a la raíz del repo) ---
    directorio_datos: Path = Path("data")
    ruta_modelo: Path = Path("data/processed/modelo_propagacion.joblib")
    ruta_modelo_profundo: Path = Path("modelos/propagacion_profundo.pt")
    ruta_detector: Path = Path("modelos/detector_temporal.pt")
    ruta_reporte: Path = Path("modelos/reporte.json")
    ruta_dataset_csv: Path | None = None

    # --- Entrenamiento ---
    n_muestras_sinteticas: int = Field(6000, ge=500, le=200_000)
    n_arboles: int = Field(150, ge=10, le=1000)
    semilla_aleatoria: int = 42
    reentrenar_al_iniciar: bool = False
    # Si faltan los pesos profundos, entrenarlos en segundo plano al arrancar
    entrenar_profundo_al_iniciar: bool = True
    n_miembros_ensemble: int = Field(5, ge=2, le=20)
    epocas_profundo: int = Field(120, ge=5, le=1000)
    n_secuencias_detector: int = Field(1500, ge=100, le=50_000)
    epocas_detector: int = Field(25, ge=1, le=500)

    # --- Operación ---
    frecuencia_sensores_hz: float = Field(10.0, gt=0, le=1000)
    # Espera a DL/detector antes de aceptar tráfico (útil en tests; en producción arranca en segundo plano)
    esperar_modelos_opcionales: bool = False
    max_conexiones_ws: int = Field(50, ge=1, le=10_000)

    @field_validator(
        "directorio_datos", "ruta_modelo", "ruta_modelo_profundo", "ruta_detector",
        "ruta_reporte", "ruta_dataset_csv", mode="after",
    )
    @classmethod
    def _resolver_ruta(cls, ruta: Path | None) -> Path | None:
        """Convierte rutas relativas en absolutas respecto a la raíz del repo."""
        if ruta is None or ruta.is_absolute():
            return ruta
        return (RAIZ_PROYECTO / ruta).resolve()


@lru_cache(maxsize=1)
def obtener_configuracion() -> Configuracion:
    """Devuelve la configuración (cacheada). Tests: `.cache_clear()` tras cambiar env."""
    return Configuracion()
