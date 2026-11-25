"""Content IDs like JD-R-003 (series code, format letter, 3-digit number)."""
from __future__ import annotations

import re
import sqlite3

FORMAT_LETTERS = {"reel": "R", "short": "S", "long": "L"}
_ID_RE = re.compile(r"^([A-Z]{2,4})-([RSL])-(\d{3,})$")


def parse_content_id(content_id: str) -> tuple[str, str, int]:
    m = _ID_RE.match(content_id)
    if not m:
        raise ValueError(f"Not a content ID: {content_id!r}")
    return m.group(1), m.group(2), int(m.group(3))


def next_content_id(conn: sqlite3.Connection, series: str, fmt: str) -> str:
    letter = FORMAT_LETTERS[fmt]
    prefix = f"{series}-{letter}-"
    rows = conn.execute("SELECT id FROM content WHERE id LIKE ?", (prefix + "%",)).fetchall()
    highest = max((parse_content_id(r[0])[2] for r in rows), default=0)
    return f"{prefix}{highest + 1:03d}"
