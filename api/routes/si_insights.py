"""Super Intelligence: insights que resumen, clasifican e interpretan los datos de referencia."""

from __future__ import annotations

from fastapi import APIRouter

from src.insights import Insight, generar_insights

router = APIRouter(prefix="/api/v1/si-insights", tags=["insights"])


@router.get("", response_model=list[Insight])
async def insights() -> list[Insight]:
    """Insights predefinidos con fuente y estado de verificación."""
    return generar_insights()
