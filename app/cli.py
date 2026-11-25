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
