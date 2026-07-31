"""Tiny, dependency-free schema reconciliation.

We use SQLAlchemy's create_all (no Alembic) to keep this single-user tool
simple. create_all adds *new tables* but never alters existing ones, so when
we add a column to an existing table we patch it here with idempotent
ALTER TABLE ADD COLUMN statements. Safe on both SQLite and PostgreSQL.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("networking.migrations")

# table -> {column: SQL type for ADD COLUMN}
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "interactions": {
        "source": "VARCHAR(40) DEFAULT 'manual'",
        "external_id": "VARCHAR(200)",
    },
    # Ієрархія проєкт → ціль → задача: таблиці tasks і goals уже існують на
    # проді, тож нові колонки треба додати явно — create_all цього не робить.
    "tasks": {
        "kind": "VARCHAR(20) DEFAULT 'task'",
        "project_id": "INTEGER",
        "item_type": "VARCHAR(40)",
        "counterpart": "VARCHAR(120)",
        "recur": "VARCHAR(20)",
    },
    "goals": {
        "project_id": "INTEGER",
    },
    "contacts": {
        "external_ref": "VARCHAR(120)",
        "telegram_chat_id": "BIGINT",
        "tone": "VARCHAR(80)",
        "do_not_contact": "BOOLEAN DEFAULT FALSE",
        "style_examples": "TEXT",
        "importance": "INTEGER DEFAULT 0",
        "auto_reply_paused": "BOOLEAN DEFAULT FALSE",
    },
}


def ensure_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all will build it fresh with all columns
        present = {c["name"] for c in inspector.get_columns(table)}
        for column, ddl in columns.items():
            if column in present:
                continue
            stmt = f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'
            try:
                with engine.begin() as conn:
                    conn.execute(text(stmt))
                logger.info("Schema patch applied: %s", stmt)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("Schema patch failed (%s): %s", stmt, exc)
