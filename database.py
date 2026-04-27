"""SQLite layer. All queries are parameterized — never interpolate user input into SQL."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).parent / "coach.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    target_date   TEXT    NOT NULL,
    target_value  INTEGER NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS check_ins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id         INTEGER NOT NULL,
    mood            TEXT    NOT NULL,
    progress_value  INTEGER NOT NULL,
    note            TEXT    NOT NULL DEFAULT '',
    coach_message   TEXT    NOT NULL,
    coach_tone      TEXT    NOT NULL,
    coach_action    TEXT    NOT NULL DEFAULT '',
    coach_assessment TEXT   NOT NULL DEFAULT '',
    coach_next_days INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Migrations for older DBs that pre-date these columns.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(check_ins)")}
        for col, ddl in (
            ("note",             "TEXT NOT NULL DEFAULT ''"),
            ("coach_action",     "TEXT NOT NULL DEFAULT ''"),
            ("coach_assessment", "TEXT NOT NULL DEFAULT ''"),
            ("coach_next_days",  "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in existing:
                conn.execute(f"ALTER TABLE check_ins ADD COLUMN {col} {ddl}")


def create_goal(
    name: str,
    title: str,
    description: str,
    target_date: str,
    target_value: int,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO goals (name, title, description, target_date, target_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, title, description, target_date, target_value, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def list_goals(name: str | None = None) -> list[sqlite3.Row]:
    with connect() as conn:
        if name:
            rows = conn.execute(
                "SELECT * FROM goals WHERE name = ? ORDER BY created_at DESC",
                (name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM goals ORDER BY created_at DESC"
            ).fetchall()
        return rows


def get_goal(goal_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()


def update_goal_progress(goal_id: int, current_value: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE goals SET current_value = ? WHERE id = ?",
            (current_value, goal_id),
        )


def create_check_in(
    goal_id: int,
    mood: str,
    progress_value: int,
    note: str,
    coach_message: str,
    coach_tone: str,
    coach_action: str,
    coach_assessment: str,
    coach_next_days: int,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO check_ins (
                goal_id, mood, progress_value, note,
                coach_message, coach_tone, coach_action, coach_assessment, coach_next_days,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                mood,
                progress_value,
                note,
                coach_message,
                coach_tone,
                coach_action,
                coach_assessment,
                coach_next_days,
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def list_check_ins(goal_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM check_ins WHERE goal_id = ? ORDER BY created_at DESC",
            (goal_id,),
        ).fetchall()


def list_recent_check_ins(goal_id: int, limit: int = 3) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM check_ins WHERE goal_id = ? ORDER BY created_at DESC LIMIT ?",
            (goal_id, limit),
        ).fetchall()
