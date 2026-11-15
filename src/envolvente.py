"""Envolvente de entrenamiento: detecta cuándo una predicción es una extrapolación.

Un Random Forest o una red no avisan cuando se les pregunta fuera de lo que vieron:
devuelven un número con total seguridad. En seguridad contra incendios eso es
inaceptable, así que cada motor guarda los rangos de sus datos y la API los reporta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

# Margen relativo al ancho del rango: evita marcar el borde exacto por redondeo
TOLERANCIA_RELATIVA = 0.02


class Envolvente(BaseModel):
    """Rangos [min, max] por variable de entrada observados en entrenamiento."""

    limites: dict[str, tuple[float, float]] = Field(default_factory=dict)

    @classmethod
    def desde_datos(cls, datos: pd.DataFrame, columnas: tuple[str, ...] | list[str]) -> Envolvente:
        """Calcula los límites a partir de un DataFrame de entrenamiento."""
        return cls(
            limites={
                columna: (float(datos[columna].min()), float(datos[columna].max()))
                for columna in columnas
            }
        )

    def variables_fuera(self, datos: pd.DataFrame) -> list[list[str]]:
        """Para cada fila, lista de variables fuera de la envolvente (vacía si ninguna).

        Vectorizado por columna; solo las filas con extrapolación construyen lista.
        """
        n_filas = len(datos)
        resultado: list[list[str]] = [[] for _ in range(n_filas)]
        for columna, (minimo, maximo) in self.limites.items():
            if columna not in datos.columns:
                continue
            margen = (maximo - minimo) * TOLERANCIA_RELATIVA
            valores = datos[columna].to_numpy(dtype=float)
            # NaN (p. ej. sin termopar) no cuenta como extrapolación
            fuera = np.flatnonzero((valores < minimo - margen) | (valores > maximo + margen))
            for indice in fuera:
                resultado[int(indice)].append(columna)
        return resultado

    def unir(self, otra: Envolvente) -> Envolvente:
        """Envolvente que cubre ambos conjuntos (tras afinar con datos nuevos)."""
        combinados = dict(self.limites)
        for variable, (minimo, maximo) in otra.limites.items():
            if variable in combinados:
                lo, hi = combinados[variable]
                combinados[variable] = (min(lo, minimo), max(hi, maximo))
            else:
                combinados[variable] = (minimo, maximo)
        return Envolvente(limites=combinados)

    def limites_de(self, variable: str) -> tuple[float, float] | None:
        """Límites de una variable, o None si no se conoce."""
        return self.limites.get(variable)
