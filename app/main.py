"""Main FastAPI Application Entrypoint."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings


from app.db.session import engine
from app.db.models import Base
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks: create tables if not existing
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE organizers ADD COLUMN IF NOT EXISTS support_phone VARCHAR(50);"))
            await conn.execute(text("ALTER TABLE organizers ADD COLUMN IF NOT EXISTS social_links JSONB;"))
            await conn.execute(text("ALTER TABLE organizers ADD COLUMN IF NOT EXISTS username VARCHAR(100);"))
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_organizers_username ON organizers (username);"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS short_description VARCHAR(500);"))
            await conn.execute(text("ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);"))
            await conn.execute(text("ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS transaction_id VARCHAR(255);"))
            await conn.execute(text("ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS screenshot_url TEXT;"))
            await conn.execute(text("ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50);"))
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
    yield
    # Shutdown tasks


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
        "http://100.89.217.81:5173",
        "http://100.89.217.81:5174",
        settings.MINI_APP_URL,
    ],
    allow_origin_regex=r"https://.*\.ngrok-free\.app|https://.*\.ngrok\.io|http://localhost:.*|http://127\.0\.0\.1:.*|http://100\..*|http://192\.168\..*|http://10\..*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Static files mount for local upload fallback
import os
from fastapi.staticfiles import StaticFiles
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "docs": "/docs",
        "health": f"{settings.API_V1_STR}/health"
    }
