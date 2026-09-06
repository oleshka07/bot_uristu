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
        # Трекер цілей: горизонт, зріз Pers/Work, відповідальні, журнал коуча.
        "horizon": "VARCHAR(20)",
        "area": "VARCHAR(10)",
        "owner": "VARCHAR(120)",
        "owner2": "VARCHAR(120)",
        "coach_notes": "TEXT",
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


# Старий статус цілі -> новий зі словника трекера.
_GOAL_STATUS_MAP = {
    "active": "in progress",
    "paused": "postponed to next year",
    "dropped": "cancelled",
    # "done" збігається в обох словниках — переписувати нічого.
}


def _migrate_goal_status(engine: Engine, inspector) -> None:
    """Переводить goals.status з БД-енума в рядок і розширює шкалу пріоритету.

    Статусів стало сім замість чотирьох, а пріоритет — 10..100 замість 1..3.
    Обидві операції ідемпотентні: після першого прогону оновлювати нічого.
    """
    columns = {c["name"]: c for c in inspector.get_columns("goals")}
    status = columns.get("status")
    if status is None:
        return

    is_sqlite = engine.dialect.name == "sqlite"
    type_name = type(status["type"]).__name__.lower()

    if "enum" in type_name and not is_sqlite:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE goals ALTER COLUMN status "
                        "TYPE VARCHAR(40) USING status::text"
                    )
                )
            logger.info("Schema patch applied: goals.status -> VARCHAR(40)")
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("goals.status type change failed: %s", exc)
            return

    try:
        with engine.begin() as conn:
            for old, new in _GOAL_STATUS_MAP.items():
                conn.execute(
                    text("UPDATE goals SET status = :new WHERE status = :old"),
                    {"new": new, "old": old},
                )
            # 1/2/3 -> 30/60/90. Нова шкала починається з 10, тож значення
            # 1..3 у базі можуть бути тільки зі старої.
            conn.execute(
                text(
                    "UPDATE goals SET priority = priority * 30 "
                    "WHERE priority BETWEEN 1 AND 3"
                )
            )
    except Exception as exc:  # pragma: no cover - best effort
        # На SQLite стара таблиця несе CHECK-обмеження зі старими статусами,
        # і зняти його можна лише перезбиранням таблиці. Для локальної бази
        # простіше видалити файл, ніж тягнути сюди повний ребілд.
        logger.warning(
            "goals.status data migration failed (%s). "
            "Локальний SQLite: видали файл бази і дай create_all зібрати її заново.",
            exc,
        )


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

    if "goals" in existing_tables:
        _migrate_goal_status(engine, inspect(engine))
