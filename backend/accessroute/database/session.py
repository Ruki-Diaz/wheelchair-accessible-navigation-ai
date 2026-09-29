"""Database session and engine lifecycle management."""

import logging
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool, QueuePool

from accessroute.database.config import db_settings

logger = logging.getLogger(__name__)

Base = declarative_base()


def create_db_engine(url: str = None):
    """Instantiate a configured SQLAlchemy engine."""
    db_url = url or db_settings.database_url

    if db_url.startswith("sqlite"):
        # SQLite configuration
        connect_args = {"check_same_thread": False}
        if ":memory:" in db_url:
            return create_engine(
                db_url,
                connect_args=connect_args,
                poolclass=StaticPool,
                echo=db_settings.echo_sql,
            )
        engine = create_engine(
            db_url,
            connect_args=connect_args,
            echo=db_settings.echo_sql,
        )

        # Enforce foreign key constraints on SQLite
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    else:
        # PostgreSQL / PostGIS configuration
        return create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=db_settings.pool_size,
            max_overflow=db_settings.max_overflow,
            pool_timeout=db_settings.pool_timeout_s,
            echo=db_settings.echo_sql,
        )


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
