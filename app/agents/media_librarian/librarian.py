"""Scan 01_RAW_MEDIA read-only and keep the `media` table in sync.

What a scan does, per file:
  1. skip hidden files, READMEs and archives (archives are reported, not opened)
  2. if path, size and mtime are unchanged since last scan: skip (fast re-scan)
  3. SHA-256 the file (opened 'rb', never written)
  4. probe metadata (ffprobe / EXIF), derive series/trip/day from the folder
  5. privacy class from config/privacy.yaml (FNEI folder -> confidential)
  6. flag duplicates (same hash as an earlier file) and quality notes
  7. thumbnail into cache/thumbs (and optional proxy into cache/proxies)

A file whose content changed is marked status='changed' (original hash kept,
nothing is "fixed"). A catalogued file that disappeared is marked 'missing'.
No AI calls happen here; scene tagging comes later and only for
non-confidential media.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.core.privacy import classify
from app.media.probe import ProbeError, kind_of, probe
from app.media.thumbs import photo_thumbnail, video_proxy, video_thumbnail

log = logging.getLogger("hq.librarian")

SKIP_NAMES = {"readme.md", "desktop.ini", "thumbs.db"}
SHORT_CLIP_S = 2.0


@dataclass
class ScanResult:
    added: list[str] = field(default_factory=list)
    unchanged: int = 0
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    duplicates: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (rel_path, reason)
    errors: list[tuple[str, str]] = field(default_factory=list)


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def _location(rel_parts: tuple[str, ...], settings: Settings) -> tuple[str | None, str | None, str | None]:
    """(series code, trip folder, day folder) from the path under 01_RAW_MEDIA."""
    if not rel_parts:
        return None, None, None
    top = rel_parts[0]
    series = next((s["code"] for s in settings.settings.get("series", []) if s.get("raw_folder") == top), None)
    if series:
        day = rel_parts[1] if len(rel_parts) > 2 else None
        return series, top, day
    if top.lower() == "previous trips":
        trip = rel_parts[1] if len(rel_parts) > 2 else None
        return None, trip, None
    return None, top, None


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def scan(
    settings: Settings,
    conn,
    *,
    subpath: str | None = None,
    proxies: bool = False,
    thumbnails: bool = True,
) -> ScanResult:
    raw = settings.raw_media
    root = (raw / subpath) if subpath else raw
    if not root.is_dir():
        raise FileNotFoundError(f"Not a folder: {root}")
    res = ScanResult()
    seen: set[str] = set()

    for path in _iter_files(root):
        rel_raw = path.relative_to(raw)
        rel = path.relative_to(settings.media_root).as_posix()
        name = path.name
        if name.startswith(".") or name.lower() in SKIP_NAMES:
            continue
        kind = kind_of(path)
        if kind == "archive":
            res.skipped.append((rel, f"archive ({path.stat().st_size / 1e6:.0f} MB), not opened"))
            continue
        if kind == "other":
            res.skipped.append((rel, "unknown file type"))
            continue
        seen.add(rel)
        st = path.stat()
        row = conn.execute("SELECT id, sha256, size_bytes, mtime_ns FROM media WHERE rel_path = ?", (rel,)).fetchone()
        if row and row["size_bytes"] == st.st_size and row["mtime_ns"] == st.st_mtime_ns:
            res.unchanged += 1
            conn.execute("UPDATE media SET status='ok' WHERE id=? AND status='missing'", (row["id"],))
            continue

        try:
            digest = sha256_file(path)
        except OSError as exc:
            res.errors.append((rel, f"read failed: {exc}"))
            continue

        if row:
            if row["sha256"] != digest:
                conn.execute("UPDATE media SET status='changed' WHERE id=?", (row["id"],))
                res.changed.append(rel)
                log.warning("original changed on disk: %s", rel)
            else:  # touched but identical
                conn.execute("UPDATE media SET mtime_ns=?, status='ok' WHERE id=?", (st.st_mtime_ns, row["id"]))
                res.unchanged += 1
            continue

        try:
            info = probe(path)
        except ProbeError as exc:
            res.errors.append((rel, str(exc)))
            continue

        notes = list(info.notes)
        if info.kind == "video" and info.duration_s is not None and info.duration_s < SHORT_CLIP_S:
            notes.append("very_short")
        if info.vfr:
            notes.append("variable_frame_rate")
        if info.hdr:
            notes.append("hdr_needs_tonemap")
        if info.gps_lat is not None:
            notes.append("has_gps")
        if info.motion_photo:
            notes.append("motion_photo")

        series, trip, day = _location(rel_raw.parts, settings)
        privacy = classify(settings, path)
        dup = conn.execute(
            "SELECT id, rel_path FROM media WHERE sha256=? AND duplicate_of IS NULL ORDER BY id LIMIT 1", (digest,)
        ).fetchone()

        cur = conn.execute(
            """INSERT INTO media (rel_path, sha256, size_bytes, mtime_ns, kind, duration_s, width, height, rotation,
                   orientation, fps, vfr, vcodec, acodec, hdr, captured_at, gps_lat, gps_lon, camera_model,
                   motion_photo, series, trip_folder, day_folder, privacy_class, duplicate_of, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rel, digest, st.st_size, st.st_mtime_ns, info.kind, info.duration_s, info.width, info.height,
             info.rotation, info.orientation, info.fps, int(info.vfr), info.vcodec, info.acodec, int(info.hdr),
             info.captured_at, info.gps_lat, info.gps_lon, info.camera_model, int(info.motion_photo),
             series, trip, day, privacy, dup["id"] if dup else None, json.dumps(notes)),
        )
        media_id = cur.lastrowid
        res.added.append(rel)
        if dup:
            res.duplicates.append((rel, dup["rel_path"]))

        key = digest[:16]
        if thumbnails and not dup:
            try:
                if info.kind == "video":
                    t = video_thumbnail(settings, path, key, info.duration_s)
                elif info.kind == "photo":
                    t = photo_thumbnail(settings, path, key)
                else:
                    t = None
                if t:
                    conn.execute("UPDATE media SET thumb_path=? WHERE id=?",
                                 (t.relative_to(settings.project_root).as_posix(), media_id))
            except Exception as exc:  # thumbnail failure must not stop the catalogue
                res.errors.append((rel, f"thumbnail: {exc}"))
        if proxies and info.kind == "video" and not dup:
            try:
                p = video_proxy(settings, path, key)
                conn.execute("UPDATE media SET proxy_path=? WHERE id=?",
                             (p.relative_to(settings.project_root).as_posix(), media_id))
            except Exception as exc:
                res.errors.append((rel, f"proxy: {exc}"))
        conn.commit()

    # mark catalogued files under this root that are gone
    prefix = root.relative_to(settings.media_root).as_posix().rstrip("/") + "/"
    for r in conn.execute("SELECT id, rel_path FROM media WHERE rel_path LIKE ? AND status != 'missing'",
                          (prefix + "%",)).fetchall():
        if r["rel_path"] not in seen and not (settings.media_root / r["rel_path"]).exists():
            conn.execute("UPDATE media SET status='missing' WHERE id=?", (r["id"],))
            res.missing.append(r["rel_path"])
    conn.commit()
    return res


def verify(settings: Settings, conn) -> dict[str, list[str]]:
    """Re-hash every catalogued original. Reports; never modifies files."""
    out: dict[str, list[str]] = {"ok": [], "changed": [], "missing": []}
    for r in conn.execute("SELECT id, rel_path, sha256 FROM media").fetchall():
        p = settings.media_root / r["rel_path"]
        if not p.exists():
            status = "missing"
        elif sha256_file(p) != r["sha256"]:
            status = "changed"
        else:
            status = "ok"
        conn.execute("UPDATE media SET status=?, verified_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                     (status, r["id"]))
        out[status].append(r["rel_path"])
    conn.commit()
    return out
