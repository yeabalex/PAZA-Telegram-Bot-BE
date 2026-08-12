"""V1 API Router router aggregation."""

from fastapi import APIRouter
from app.api.v1.endpoints import health, scraper, users, events, organizers, notifications

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(scraper.router, prefix="/scraper", tags=["Scraper Pipeline"])
api_router.include_router(users.router, prefix="/users", tags=["Users & Authentication"])
api_router.include_router(events.router, prefix="/events", tags=["Events Feed"])
api_router.include_router(organizers.router, prefix="/organizers", tags=["Organizers Portal"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications & Broadcasts"])



