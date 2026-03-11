from __future__ import annotations

import json
import logging
from collections.abc import Generator
from datetime import datetime

from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return _engine


def _migrate_add_dtstart_utc(engine: Engine) -> None:
    try:
        columns = [c["name"] for c in inspect(engine).get_columns("source_items")]
    except Exception:
        return
    if not columns:
        return
    if "dtstart_utc" in columns:
        return

    with engine.connect() as connection:
        connection.execute(text("ALTER TABLE source_items ADD COLUMN dtstart_utc TIMESTAMP NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_source_items_dtstart_utc ON source_items (dtstart_utc)"))
        connection.commit()

        rows = connection.execute(
            text("SELECT id, raw_metadata FROM source_items WHERE source_type = 'calendar'")
        ).fetchall()
        backfilled = 0
        for row in rows:
            try:
                meta = json.loads(row[1])
                dtstart_str = meta.get("dtstart", "")
                if not dtstart_str or dtstart_str.endswith("(all-day)"):
                    continue
                parsed = datetime.fromisoformat(dtstart_str)
                connection.execute(
                    text("UPDATE source_items SET dtstart_utc = :dt WHERE id = :id"),
                    {"dt": parsed, "id": row[0]},
                )
                backfilled += 1
            except Exception:
                logger.warning("Failed to backfill dtstart_utc for row %s", row[0])
                continue
        connection.commit()
        logger.info("Backfilled dtstart_utc for %d rows", backfilled)


def _migrate_add_flush_attempts(engine: Engine) -> None:
    try:
        columns = [c["name"] for c in inspect(engine).get_columns("held_notifications")]
    except Exception:
        return
    if not columns:
        return
    if "flush_attempts" in columns:
        return
    with engine.connect() as connection:
        connection.execute(text("ALTER TABLE held_notifications ADD COLUMN flush_attempts INTEGER DEFAULT 0 NOT NULL"))
        connection.commit()
    logger.info("Added flush_attempts column to held_notifications")


def _migrate_add_embedded_column(engine: Engine) -> None:
    try:
        columns = [c["name"] for c in inspect(engine).get_columns("source_items")]
    except Exception:
        return
    if not columns:
        return
    if "embedded" in columns:
        return
    with engine.connect() as connection:
        connection.execute(text("ALTER TABLE source_items ADD COLUMN embedded BOOLEAN DEFAULT 0 NOT NULL"))
        result = connection.execute(text("UPDATE source_items SET embedded = 1"))
        connection.commit()
        logger.info("Added embedded column to source_items, marked %d existing rows as embedded", result.rowcount)


def init_db() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _migrate_add_dtstart_utc(engine)
    _migrate_add_flush_attempts(engine)
    _migrate_add_embedded_column(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
