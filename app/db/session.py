"""Database session initialization module."""

import re
import ssl as ssl_module
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# Convert postgresql:// to postgresql+asyncpg:// if needed
database_url = settings.sqlalchemy_database_uri
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Detect if SSL is required from the URL params, then strip sslmode/ssl params
# because asyncpg doesn't understand them as URL query parameters.
_needs_ssl = bool(re.search(r"[?&]sslmode=", database_url) or re.search(r"[?&]ssl=", database_url))
database_url = re.sub(r"[?&]sslmode=[^&]*", "", database_url)
database_url = re.sub(r"[?&]ssl=[^&]*", "", database_url)

# Build connect_args for asyncpg SSL & Server settings
_connect_args = {
    "server_settings": {
        "jit": "off",
    },
    "command_timeout": 60,
    "prepared_statement_cache_size": 0,
}
if _needs_ssl:
    _ssl_ctx = ssl_module.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl_module.CERT_NONE
    _connect_args["ssl"] = _ssl_ctx

engine = create_async_engine(
    database_url,
    echo=False,
    future=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=60,
    pool_timeout=15,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing asynchronous database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
