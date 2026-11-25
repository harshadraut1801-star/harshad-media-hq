"""SQLite connection and migrations.

Migrations are numbered SQL files in db/migrations/ (0001_init.sql, ...),
applied in order inside a transaction each, and recorded in schema_version.
Never edit an applied migration; add a new one.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.core.config import Settings
from app.core.paths import safe_write_path

_MIGRATION_RE = re.compile(r"^(\d{4})_[\w-]+\.sql$")


def connect(settings: Settings) -> sqlite3.Connection:
    db_path = safe_write_path(settings, settings.database)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _migrations_dir(settings: Settings) -> Path:
    return settings.project_root / "db" / "migrations"


def _available(settings: Settings) -> list[tuple[int, Path]]:
    found = []
    for f in sorted(_migrations_dir(settings).glob("*.sql")):
        m = _MIGRATION_RE.match(f.name)
        if not m:
            raise ValueError(f"Bad migration filename: {f.name} (want NNNN_name.sql)")
        found.append((int(m.group(1)), f))
    numbers = [n for n, _ in found]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Duplicate migration numbers in db/migrations/")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def migrate(settings: Settings, conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Returns the filenames applied."""
    current = schema_version(conn)
    applied: list[str] = []
    for number, path in _available(settings):
        if number <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.execute("BEGIN")
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)", (number, path.name))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(path.name)
    return applied


def _split_sql(sql: str) -> list[str]:
    """Split on ';' at end of statement. Good enough for plain DDL (no triggers yet)."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
