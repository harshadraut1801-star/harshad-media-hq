from app.core.ids import next_content_id
from app.db import connect, migrate, schema_version


def test_migrate_creates_schema_and_is_idempotent(settings):
    conn = connect(settings)
    assert migrate(settings, conn) == ["0001_init.sql"]
    assert schema_version(conn) == 1
    assert migrate(settings, conn) == []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("media", "content", "assets", "approvals", "posts", "metrics", "jobs", "llm_calls", "events"):
        assert t in tables


def test_privacy_class_constraint(settings):
    import sqlite3

    import pytest

    conn = connect(settings)
    migrate(settings, conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO media (rel_path, sha256, size_bytes, kind, privacy_class) VALUES ('a','b',1,'video','secret')"
        )


def test_next_content_id(settings):
    conn = connect(settings)
    migrate(settings, conn)
    assert next_content_id(conn, "JD", "reel") == "JD-R-001"
    conn.execute("INSERT INTO content (id, series, format) VALUES ('JD-R-001','JD','reel')")
    conn.execute("INSERT INTO content (id, series, format) VALUES ('JD-R-009','JD','reel')")
    assert next_content_id(conn, "JD", "reel") == "JD-R-010"
    assert next_content_id(conn, "JD", "short") == "JD-S-001"
