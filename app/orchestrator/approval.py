"""Human approval, tied to exact file contents.

submit():  rough_cut/rejected -> pending_approval, records which files are up for review
approve(): human only. Hashes the video (and caption/thumbnail if present) *at
           approval time*, stores them in `approvals`, copies the package into
           07_READY_TO_PUBLISH/<Series>/<id>/ with manifest.json, -> approved.
reject():  human only, note required, -> rejected.
check():   re-hashes the package; if anything differs from what was approved the
           approval is void and the content drops back to pending_approval.
           The publisher must call check() and refuse unless it returns ok.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.paths import open_for_write, safe_write_path

from .state import TransitionError, current_state, transition


class ApprovalError(RuntimeError):
    pass


@dataclass
class Package:
    content_id: str
    series: str
    video: Path
    caption: Path | None
    thumbnail: Path | None

    def files(self) -> dict[str, Path]:
        out = {"video": self.video}
        if self.caption:
            out["caption"] = self.caption
        if self.thumbnail:
            out["thumbnail"] = self.thumbnail
        return out


def human_actor() -> str:
    return f"human:{getpass.getuser()}"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while b := fh.read(4 * 1024 * 1024):
            h.update(b)
    return h.hexdigest()


def _series_name(settings: Settings, code_or_name: str) -> str:
    for s in settings.settings.get("series", []):
        if code_or_name in (s.get("code"), s.get("name")):
            return s["name"]
    return code_or_name


def find_package(settings: Settings, content_id: str, series: str, version: int | None = None) -> Package:
    """Latest (or given) rendered version + optional caption/thumbnail by convention:
    03_AI_SCRIPTS/<Series>/<id>/caption.txt, 06_THUMBNAILS/<Series>/<id>/thumbnail.jpg"""
    name = _series_name(settings, series)
    folder = settings.media_path("edited") / name / content_id
    vids = sorted(folder.glob(f"{content_id}_v*.mp4"), key=lambda p: int(p.stem.rsplit("_v", 1)[1]))
    if version is not None:
        vids = [v for v in vids if v.stem == f"{content_id}_v{version}"]
    if not vids:
        raise ApprovalError(f"No rendered video found for {content_id} in {folder}")
    cap = settings.media_path("scripts") / name / content_id / "caption.txt"
    thumbs = [settings.media_path("thumbnails") / name / content_id / f"thumbnail.{e}" for e in ("jpg", "png")]
    return Package(content_id, name, vids[-1], cap if cap.is_file() else None,
                   next((t for t in thumbs if t.is_file()), None))


def _ensure_content(conn, settings, content_id: str, series: str, fmt: str = "reel") -> None:
    if conn.execute("SELECT 1 FROM content WHERE id=?", (content_id,)).fetchone() is None:
        code = next((s["code"] for s in settings.settings.get("series", [])
                     if series in (s.get("code"), s.get("name"))), series)
        conn.execute("INSERT INTO content (id, series, format, state) VALUES (?,?,?, 'rough_cut')",
                     (content_id, code, fmt))
        conn.execute("INSERT INTO events (entity, entity_id, to_state, actor, note) VALUES "
                     "('content', ?, 'rough_cut', 'system', 'registered from rendered file')", (content_id,))
        conn.commit()


def submit(settings, conn, content_id: str, series: str, version: int | None = None, *, actor: str) -> Package:
    pkg = find_package(settings, content_id, series, version)
    _ensure_content(conn, settings, content_id, series)
    if current_state(conn, content_id) != "pending_approval":
        transition(conn, content_id, "pending_approval", actor=actor, note=f"submitted {pkg.video.name}")
    return pkg


def approve(settings, conn, content_id: str, series: str, *, actor: str, checklist_confirmed: bool,
            version: int | None = None, note: str | None = None) -> Path:
    if not checklist_confirmed:
        raise ApprovalError("Confirm the pre-publish checklist first (privacy.yaml: pre_publish_checklist)")
    if not actor.startswith("human:"):
        raise ApprovalError("Only a person can approve")
    pkg = find_package(settings, content_id, series, version)
    _ensure_content(conn, settings, content_id, series)
    state = current_state(conn, content_id)
    if state != "pending_approval":
        raise ApprovalError(f"{content_id} is '{state}'. Run `hq submit` first so it is pending approval.")
    _refuse_confidential(settings, conn, content_id)

    hashes = {k: _sha(p) for k, p in pkg.files().items()}
    ready = settings.media_path("ready") / pkg.series / content_id
    if ready.exists():
        for old in ready.iterdir():
            safe_write_path(settings, old).unlink()
    copied = {}
    for kind, src in pkg.files().items():
        dst = safe_write_path(settings, ready / src.name)
        shutil.copy2(src, dst)
        if _sha(dst) != hashes[kind]:
            raise ApprovalError(f"Copy of {src.name} does not match the original; approval aborted")
        copied[kind] = dst.name
    conn.execute("INSERT INTO approvals (content_id, asset_hashes, decision, note, decided_by) VALUES (?,?,?,?,?)",
                 (content_id, json.dumps(hashes), "approved", note, actor))
    approval_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    manifest = ready / "manifest.json"
    with open_for_write(settings, manifest) as fh:
        json.dump({"content_id": content_id, "series": pkg.series, "approval_id": approval_id,
                   "approved_by": actor, "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "files": copied, "sha256": hashes, "note": note,
                   "rule": "Publisher must verify these hashes before upload. Any change voids this approval."},
                  fh, indent=2)
    transition(conn, content_id, "approved", actor=actor, note=f"approval #{approval_id}: {pkg.video.name}")
    return ready


def reject(settings, conn, content_id: str, *, actor: str, note: str) -> None:
    if not note or not note.strip():
        raise ApprovalError("Say what to change: a note is required when rejecting")
    state = current_state(conn, content_id)
    if state != "pending_approval":
        raise ApprovalError(f"{content_id} is '{state}', not pending approval")
    conn.execute("INSERT INTO approvals (content_id, asset_hashes, decision, note, decided_by) VALUES (?,?,?,?,?)",
                 (content_id, "{}", "rejected", note, actor))
    transition(conn, content_id, "rejected", actor=actor, note=note)


def check(settings, conn, content_id: str) -> tuple[bool, str]:
    """True only if the content is approved and the ready package still matches the approved hashes."""
    try:
        state = current_state(conn, content_id)
    except TransitionError as exc:
        return False, str(exc)
    row = conn.execute("SELECT id, asset_hashes FROM approvals WHERE content_id=? AND decision='approved' "
                       "ORDER BY id DESC LIMIT 1", (content_id,)).fetchone()
    if state not in ("approved", "scheduled") or row is None:
        return False, f"{content_id} is not approved (state: {state})"
    code = conn.execute("SELECT series FROM content WHERE id=?", (content_id,)).fetchone()[0]
    ready = settings.media_path("ready") / _series_name(settings, code) / content_id
    manifest_path = ready / "manifest.json"
    if not manifest_path.is_file():
        return _void(conn, content_id, "manifest.json missing from ready package")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    approved = json.loads(row["asset_hashes"])
    for kind, fname in manifest.get("files", {}).items():
        f = ready / fname
        if not f.is_file():
            return _void(conn, content_id, f"{fname} missing from ready package")
        if _sha(f) != approved.get(kind):
            return _void(conn, content_id, f"{fname} changed after approval")
    if set(manifest.get("files", {})) != set(approved):
        return _void(conn, content_id, "package contents differ from what was approved")
    return True, f"approval #{row['id']} valid"


def _void(conn, content_id: str, why: str) -> tuple[bool, str]:
    transition(conn, content_id, "pending_approval", actor="system", note=f"approval void: {why}")
    return False, f"approval void: {why}"


def _refuse_confidential(settings, conn, content_id: str) -> None:
    rows = conn.execute("SELECT m.rel_path FROM content_media cm JOIN media m ON m.id=cm.media_id "
                        "WHERE cm.content_id=? AND m.privacy_class='confidential'", (content_id,)).fetchall()
    if rows:
        raise ApprovalError(f"{content_id} uses confidential media: {[r[0] for r in rows]}")


def pending(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT c.id, c.series, c.format, c.title, c.state, "
        "(SELECT MAX(at) FROM events e WHERE e.entity_id=c.id) AS updated FROM content c "
        "WHERE c.state NOT IN ('published','measured') ORDER BY c.id")]
