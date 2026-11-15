"""Variables físicas que el modelo actual NO incluye (roadmap público).

Se expone por la API para que quien evalúe IGNIS vea qué falta y por qué importa:
declarar los límites del modelo es parte del producto, no una confesión incómoda.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class VariablePendiente(BaseModel):
    """Una variable ausente del modelo y la razón física de incluirla."""

    variable: str
    por_que_importa: str
    prioridad: Literal["alta", "media"]
    version_objetivo: str


VARIABLES_NO_INCLUIDAS: tuple[VariablePendiente, ...] = (
    VariablePendiente(
        variable="Geometría del confinamiento",
        por_que_importa="Un pasillo estrecho y un módulo amplio cambian la dinámica del flujo y la acumulación de calor.",
        prioridad="alta", version_objetivo="v2.0",
    ),
    VariablePendiente(
        variable="Orientación del material respecto al flujo",
        por_que_importa="Flujo concurrente u opuesto determina el modo de propagación. la versión actual solo lo codifica como "
                        "categoría, sin ángulos ni geometría de la muestra.",
        prioridad="alta", version_objetivo="v2.0",
    ),
    VariablePendiente(
        variable="Historial de ignición",
        por_que_importa="Una fuente puntual (cortocircuito) y un calentamiento general producen fuegos distintos.",
        prioridad="media", version_objetivo="v2.1",
    ),
    VariablePendiente(
        variable="Composición detallada del combustible",
        por_que_importa="Densidad, conductividad térmica y calor de gasificación gobiernan la velocidad de llama; "
                        "hoy solo hay tres materiales de referencia.",
        prioridad="media", version_objetivo="v2.1",
    ),
)
