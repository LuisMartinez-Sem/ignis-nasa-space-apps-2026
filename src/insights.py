"""Insights de 'Super Intelligence': resumen, clasificación e interpretación a partir de las anclas y del modelo.

Los textos son predefinidos (no generados en vivo). Los números salen de `data/anclas_reales.json`; cada insight
declara su fuente y si IGNIS la verificó.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.dataset_sintetico import cargar_anclas
from src.predictor import VELOCIDAD_NORMALIZACION_MM_S

Tipo = Literal["Riesgo", "Alerta", "Clasificación", "Interpretación", "Límite"]


class Insight(BaseModel):
    tipo: Tipo
    texto: str
    fuente: str
    verificacion: Literal["no_verificado_por_ignis", "modelo_ignis", "diseno_de_producto"]


def generar_insights() -> list[Insight]:
    """Construye la lista de insights con los valores vigentes de las anclas."""
    valor = {a["id"]: a["valor"] for a in cargar_anclas()}
    conc, opu = valor["saffire-i-concurrente"], valor["saffire-i-opuesto"]
    lo, hi = valor["flex-cool-flame-ventana"]
    return [
        Insight(tipo="Riesgo", verificacion="modelo_ignis",
                texto="El oxígeno acelera la propagación: cada punto extra de O₂ vuelve la llama más rápida y más difícil de frenar, así que subir el O₂ de cabina es el cambio que más pesa en el riesgo. El modelo lo muestra como tendencia; Saffire-I no fija un umbral en 24 %.",
                fuente="Tendencia cualitativa de la literatura de propagación en microgravedad; modelo IGNIS"),
        Insight(tipo="Clasificación", verificacion="no_verificado_por_ignis",
                texto=f"El sentido de la ventilación importa: con el flujo a favor de la llama ({conc} mm/s) el fuego avanza ×{conc / opu:.2f} más rápido que contra ella ({opu} mm/s). Ventilar hacia el foco empeora el incidente; apagar o invertir el flujo lo frena.",
                fuente="Saffire-I (NASA NTRS 20170002628; cifras no localizadas en el NTRS por IGNIS)"),
        Insight(tipo="Alerta", verificacion="no_verificado_por_ignis",
                texto=f"Una cabina que parece segura puede no estarlo: entre {lo:.0f} y {hi:.0f} K la llama fría arde sin luz visible, ninguna cámara común la delata y puede reavivarse. Por eso IGNIS vigila la temperatura IR y no solo la imagen.",
                fuente="FLEX (Nayagam)"),
        Insight(tipo="Interpretación", verificacion="diseno_de_producto",
                texto=f"Un índice alto significa, sobre todo, que el fuego se propagaría (55 %), que lo haría rápido (30 %, saturado a {VELOCIDAD_NORMALIZACION_MM_S} mm/s) y, en menor medida, que hay llama fría oculta (15 %). Léelo como prioridad de respuesta, no como probabilidad de incendio.",
                fuente="Diseño de producto IGNIS (docs/science.md); pendiente de validación experta"),
        Insight(tipo="Límite", verificacion="no_verificado_por_ignis",
                texto=f"No extrapoles a 1-g ni a otros materiales: Saffire-II (silicona, 1-g, {valor['saffire-ii-silicona-1g']} mm/s) y los tiempos de combustión de Saffire-I son solo referencia y no entrenan el modelo, así que el modelo es menos fiable fuera de SIBAL y microgravedad.",
                fuente="PSI-98/99 (CSV aportado por el equipo)"),
    ]
