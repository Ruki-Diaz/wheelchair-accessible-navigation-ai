"""Database configuration and connection management for AccessRoute AI.

Supports both PostgreSQL/PostGIS (for production) and SQLite (for development and tests).
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field

_backend_data_dir = Path(__file__).resolve().parent.parent.parent / "data"
_backend_data_dir.mkdir(parents=True, exist_ok=True)
_default_sqlite_url = f"sqlite:///{_backend_data_dir / 'accessroute.db'}"


class DatabaseSettings(BaseModel):
    """Database connection and pool settings."""

    database_url: str = Field(
        default_factory=lambda: os.getenv("DATABASE_URL", _default_sqlite_url)
    )
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=20, ge=0, le=100)
    pool_timeout_s: float = Field(default=30.0, ge=1.0)
    echo_sql: bool = Field(default_factory=lambda: os.getenv("SQL_ECHO", "false").lower() == "true")
    enable_postgis: bool = Field(default_factory=lambda: os.getenv("ENABLE_POSTGIS", "true").lower() == "true")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql") or self.database_url.startswith("postgres")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


# Global database settings singleton
db_settings = DatabaseSettings()
