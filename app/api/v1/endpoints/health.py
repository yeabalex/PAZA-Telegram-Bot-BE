"""Health check endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    environment: str


@router.get("/health", response_model=HealthResponse, summary="Health Check")
async def health_check():
    """Verify application health and environment context."""
    from app.core import settings
    return HealthResponse(
        status="ok",
        environment=settings.ENVIRONMENT
    )
