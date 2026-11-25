"""`hq` command line. Entry point for humans, n8n and the dashboard.

Commands:
  hq init               create missing folders, create/migrate the database
  hq status             show paths, schema version and counts
  hq doctor             check Python, FFmpeg/ffprobe, config, folders, .env hygiene
  hq classify PATH...   show the privacy class a media path would get
  hq scan [--path SUB] [--proxies] [--no-thumbs]
                        catalogue 01_RAW_MEDIA read-only (Media Librarian)
  hq verify             re-hash every catalogued original; report changed/missing
  hq catalogue          print the summary and write cache/reports/catalogue.html
  hq render EDL.yaml    render a draft from an edit list into 05_EDITED_VIDEOS (Video Editor)
  hq review             list content and where each piece is in the pipeline
  hq submit ID [--version N]   put the latest render up for approval
  hq approve ID         YOU approve: shows the privacy checklist, hashes the files, fills 07_READY_TO_PUBLISH
  hq reject ID --note "what to change"
  hq check ID           verify an approved package is unchanged (the publisher runs this)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import ConfigError, load_settings
from app.core.paths import is_raw_media
from app.core.privacy import classify
from app.db import connect, migrate, schema_version

MEDIA_KEYS = ("raw_media", "selected", "scripts", "voiceovers", "edited", "thumbnails", "ready", "published")
COUNT_TABLES = ("media", "content", "assets", "approvals", "posts", "jobs", "llm_calls")


def cmd_init(args) -> int:
    s = load_settings(args.root)
    created = []
    for key in MEDIA_KEYS:
        p = s.media_path(key)
        if not p.exists():
            p.mkdir(parents=True)  # creating an empty folder is not writing into raw media
            created.append(str(p))
    for key in ("cache", "logs"):
        s.project_path(key).mkdir(parents=True, exist_ok=True)
    conn = connect(s)
    applied = migrate(s, conn)
    print(f"Database: {s.database}")
    print(f"Migrations applied: {', '.join(applied) if applied else 'none (up to date)'}")
    print(f"Schema version: {schema_version(conn)}")
    if created:
        print("Created folders:\n  " + "\n  ".join(created))
    return 0


def cmd_status(args) -> int:
    s = load_settings(args.root)
    print(f"Project root : {s.project_root}")
    print(f"Media root   : {s.media_root}")
    print(f"Raw media    : {s.raw_media} (read-only)")
    print(f"AI budget    : ${s.monthly_budget_usd:.2f}/month" + ("  [paid AI calls blocked]" if s.monthly_budget_usd <= 0 else ""))
    if not s.database.exists():
        print("Database     : not created yet, run `hq init`")
        return 0
    conn = connect(s)
    print(f"Database     : {s.database} (schema v{schema_version(conn)})")
    for t in COUNT_TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<10} {n}")
    return 0


def _tool_version(name: str) -> str | None:
    exe = shutil.which(name)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15).stdout
        return out.splitlines()[0] if out else exe
    except (OSError, subprocess.TimeoutExpired):
        return exe


def cmd_doctor(args) -> int:
    problems = 0

    def report(ok: bool, label: str, detail: str = "") -> None:
        nonlocal problems
        problems += 0 if ok else 1
        print(f"[{'OK' if ok else '!!'}] {label}" + (f": {detail}" if detail else ""))

    report(sys.version_info >= (3, 11), "Python >= 3.11", sys.version.split()[0])
    try:
        s = load_settings(args.root)
        report(True, "Config loads", str(s.project_root))
    except ConfigError as exc:
        report(False, "Config loads", str(exc))
        return 1
    for tool in ("ffmpeg", "ffprobe"):
        v = _tool_version(tool)
        report(v is not None, tool, v or "not found on PATH (install FFmpeg)")
    for key in MEDIA_KEYS:
        p = s.media_path(key)
        report(p.is_dir(), f"folder {key}", str(p))
    fnei = [p for p in s.privacy.get("confidential_paths", [])]
    for rel in fnei:
        report((s.media_root / rel).is_dir(), "confidential folder present", rel)
    env_file = s.project_root / ".env"
    report(True, ".env", "present" if env_file.exists() else "absent (fine until a task needs keys)")
    gi = s.project_root / ".gitignore"
    report(gi.exists() and ".env" in gi.read_text(encoding="utf-8"), ".env is git-ignored")
    print("All good." if problems == 0 else f"{problems} problem(s) found.")
    return 0 if problems == 0 else 1


def cmd_classify(args) -> int:
    s = load_settings(args.root)
    for raw in args.paths:
        p = Path(raw)
        if not p.is_absolute():
            p = s.media_root / p
        where = "raw" if is_raw_media(s, p) else "derived"
        print(f"{classify(s, p):<15} {where:<8} {p}")
    return 0


def _open_db(s):
    conn = connect(s)
    migrate(s, conn)
    return conn


def cmd_scan(args) -> int:
    from app.agents.media_librarian import scan
    from app.agents.media_librarian.report import console_summary, summarise, write_html
    from app.core.logging import setup_logging

    s = load_settings(args.root)
    setup_logging(s)
    conn = _open_db(s)
    res = scan(s, conn, subpath=args.path, proxies=args.proxies, thumbnails=not args.no_thumbs)
    print(f"Added {len(res.added)}, unchanged {res.unchanged}, duplicates {len(res.duplicates)}, "
          f"skipped {len(res.skipped)}, errors {len(res.errors)}")
    for rel, why in res.skipped:
        print(f"  skipped: {rel} ({why})")
    for rel, orig in res.duplicates:
        print(f"  duplicate: {rel} = {orig}")
    for rel in res.changed:
        print(f"  !! ORIGINAL CHANGED: {rel}")
    for rel in res.missing:
        print(f"  !! MISSING: {rel}")
    for rel, err in res.errors:
        print(f"  error: {rel}: {err}")
    summary = summarise(conn)
    print(console_summary(summary))
    print(f"Report: {write_html(s, summary)}")
    return 1 if (res.changed or res.errors) else 0


def cmd_verify(args) -> int:
    from app.agents.media_librarian import verify

    s = load_settings(args.root)
    out = verify(s, _open_db(s))
    print(f"ok {len(out['ok'])}, changed {len(out['changed'])}, missing {len(out['missing'])}")
    for k in ("changed", "missing"):
        for rel in out[k]:
            print(f"  !! {k.upper()}: {rel}")
    return 0 if not (out["changed"] or out["missing"]) else 1


def cmd_catalogue(args) -> int:
    from app.agents.media_librarian.report import console_summary, summarise, write_html

    s = load_settings(args.root)
    summary = summarise(_open_db(s))
    print(console_summary(summary))
    print(f"Report: {write_html(s, summary)}")
    return 0


def cmd_render(args) -> int:
    from app.agents.video_editor import load_edl, render
    from app.agents.video_editor.edl import EDLError
    from app.agents.video_editor.render import RenderError
    from app.core.logging import setup_logging

    s = load_settings(args.root)
    setup_logging(s)
    edl_path = Path(args.edl)
    if not edl_path.is_absolute() and not edl_path.exists():
        edl_path = s.media_root / edl_path
    try:
        edl = load_edl(edl_path)
        res = render(s, _open_db(s), edl, keep_tmp=args.keep_tmp)
    except (EDLError, RenderError) as exc:
        print(f"Render failed: {exc}", file=sys.stderr)
        return 1
    print(f"Rendered {res.video} ({res.duration_s:.1f}s)")
    print(f"Review page: {res.review}")
    return 0


def _series_for(s, content_id: str) -> str:
    prefix = content_id.split("-", 1)[0]
    for ser in s.settings.get("series", []):
        if ser.get("code") == prefix:
            return ser["name"]
    raise ConfigError(f"No series with code '{prefix}' in settings.yaml")


def cmd_review(args) -> int:
    from app.orchestrator.approval import pending

    s = load_settings(args.root)
    rows = pending(_open_db(s))
    if not rows:
        print("No content yet. Render something with `hq render`, then `hq submit ID`.")
    for r in rows:
        print(f"{r['id']:<10} {r['state']:<17} {r['format']:<6} {r['title'] or ''}")
    return 0


def cmd_submit(args) -> int:
    from app.orchestrator.approval import ApprovalError, human_actor, submit

    s = load_settings(args.root)
    try:
        pkg = submit(s, _open_db(s), args.id, _series_for(s, args.id), args.version, actor=human_actor())
    except ApprovalError as exc:
        print(f"Cannot submit: {exc}", file=sys.stderr)
        return 1
    print(f"{args.id} is pending approval: {pkg.video.name}"
          + (f", caption {pkg.caption.name}" if pkg.caption else ", no caption yet")
          + (f", thumbnail {pkg.thumbnail.name}" if pkg.thumbnail else ", no thumbnail yet"))
    return 0


def cmd_approve(args) -> int:
    from app.orchestrator.approval import ApprovalError, approve, find_package, human_actor

    s = load_settings(args.root)
    series = _series_for(s, args.id)
    try:
        pkg = find_package(s, args.id, series, args.version)
    except ApprovalError as exc:
        print(f"Cannot approve: {exc}", file=sys.stderr)
        return 1
    print(f"Approving {args.id}: {pkg.video.name}")
    checklist = s.privacy.get("pre_publish_checklist", [])
    ok = args.checklist_ok
    if not ok:
        if not sys.stdin.isatty():
            print("Run this yourself in a terminal (it asks you to confirm the checklist), "
                  "or pass --checklist-ok if you have checked it.", file=sys.stderr)
            return 1
        for item in checklist:
            if input(f"  {item}? [y/N] ").strip().lower() != "y":
                print("Not approved. Fix it, re-render, and try again.")
                return 1
        ok = input(f"Type {args.id} to approve: ").strip() == args.id
        if not ok:
            print("Not approved.")
            return 1
    try:
        ready = approve(s, _open_db(s), args.id, series, actor=human_actor(), checklist_confirmed=ok,
                        version=args.version, note=args.note)
    except ApprovalError as exc:
        print(f"Cannot approve: {exc}", file=sys.stderr)
        return 1
    print(f"Approved. Package: {ready}")
    print("Nothing has been published. Publishing is a separate step that re-checks this approval.")
    return 0


def cmd_reject(args) -> int:
    from app.orchestrator.approval import ApprovalError, human_actor, reject

    s = load_settings(args.root)
    try:
        reject(s, _open_db(s), args.id, actor=human_actor(), note=args.note)
    except ApprovalError as exc:
        print(f"Cannot reject: {exc}", file=sys.stderr)
        return 1
    print(f"{args.id} rejected. Note saved: {args.note}")
    return 0


def cmd_check(args) -> int:
    from app.orchestrator.approval import check

    s = load_settings(args.root)
    ok, msg = check(s, _open_db(s), args.id)
    print(("OK: " if ok else "NOT OK: ") + msg)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hq", description="Harshad Media HQ")
    parser.add_argument("--root", help="project root (default: search upward from cwd)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create folders and database").set_defaults(func=cmd_init)
    sub.add_parser("status", help="show paths and counts").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="check environment").set_defaults(func=cmd_doctor)
    c = sub.add_parser("classify", help="privacy class of media paths")
    c.add_argument("paths", nargs="+")
    c.set_defaults(func=cmd_classify)
    sc = sub.add_parser("scan", help="catalogue raw media (read-only)")
    sc.add_argument("--path", help="subfolder of 01_RAW_MEDIA, e.g. 'Jaipur Diaries/Day 01 - Aurangabad to Indore'")
    sc.add_argument("--proxies", action="store_true", help="also make 540p proxies (slow)")
    sc.add_argument("--no-thumbs", action="store_true", help="skip thumbnails")
    sc.set_defaults(func=cmd_scan)
    sub.add_parser("verify", help="re-hash originals").set_defaults(func=cmd_verify)
    sub.add_parser("catalogue", help="summary + HTML report").set_defaults(func=cmd_catalogue)
    r = sub.add_parser("render", help="render a draft from an EDL")
    r.add_argument("edl", help="path to edl.yaml (absolute, or relative to cwd or MEDIA_ROOT)")
    r.add_argument("--keep-tmp", action="store_true", help="keep intermediate files in cache/tmp")
    r.set_defaults(func=cmd_render)
    sub.add_parser("review", help="list content and states").set_defaults(func=cmd_review)
    sm = sub.add_parser("submit", help="put latest render up for approval")
    sm.add_argument("id")
    sm.add_argument("--version", type=int)
    sm.set_defaults(func=cmd_submit)
    ap = sub.add_parser("approve", help="approve content (you only)")
    ap.add_argument("id")
    ap.add_argument("--version", type=int)
    ap.add_argument("--note")
    ap.add_argument("--checklist-ok", action="store_true", help="skip the interactive checklist (you checked it)")
    ap.set_defaults(func=cmd_approve)
    rj = sub.add_parser("reject", help="reject with a note")
    rj.add_argument("id")
    rj.add_argument("--note", required=True)
    rj.set_defaults(func=cmd_reject)
    ck = sub.add_parser("check", help="verify an approval is still valid")
    ck.add_argument("id")
    ck.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
