"""Catalogue report: console summary + an offline HTML contact sheet in cache/reports/.

Confidential items show no thumbnail in the HTML, only a CONFIDENTIAL tile.
GPS is never shown, only whether it is present.
"""
from __future__ import annotations

import html
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.paths import open_for_write

IST = timezone(timedelta(hours=5, minutes=30))


def _local(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST).strftime("%d %b %H:%M")
    except ValueError:
        return ts


def summarise(conn) -> dict:
    rows = [dict(r) for r in conn.execute(
        "SELECT m.*, COALESCE(m.thumb_path, o.thumb_path) AS thumb_path FROM media m"
        " LEFT JOIN media o ON o.id = m.duplicate_of ORDER BY m.series, m.day_folder, m.captured_at, m.rel_path")]
    by_day: dict[str, Counter] = defaultdict(Counter)
    total_video_s = 0.0
    for r in rows:
        day = r["day_folder"] or r["trip_folder"] or "(other)"
        by_day[day][r["kind"]] += 1
        by_day[day][f"{r['orientation'] or 'unknown'}"] += 1
        if r["kind"] == "video" and r["duration_s"] and not r["duplicate_of"]:
            total_video_s += r["duration_s"]
            by_day[day]["video_s"] += r["duration_s"]
    flags = Counter(n for r in rows for n in json.loads(r["notes"] or "[]"))
    return {
        "rows": rows,
        "by_day": by_day,
        "total_video_s": total_video_s,
        "privacy": Counter(r["privacy_class"] for r in rows),
        "status": Counter(r["status"] for r in rows),
        "duplicates": sum(1 for r in rows if r["duplicate_of"]),
        "flags": flags,
    }


def console_summary(s: dict) -> str:
    lines = [f"Catalogue: {len(s['rows'])} files, {s['total_video_s'] / 60:.1f} min of unique video"]
    for day, c in s["by_day"].items():
        lines.append(
            f"  {day}: {c['video']} videos ({c['video_s'] / 60:.1f} min), {c['photo']} photos"
            f" | portrait {c['portrait']}, landscape {c['landscape']}"
        )
    lines.append("  privacy: " + ", ".join(f"{k} {v}" for k, v in sorted(s["privacy"].items())))
    if s["duplicates"]:
        lines.append(f"  duplicates: {s['duplicates']}")
    bad = {k: v for k, v in s["status"].items() if k != "ok"}
    if bad:
        lines.append("  ATTENTION: " + ", ".join(f"{k} {v}" for k, v in bad.items()))
    if s["flags"]:
        lines.append("  flags: " + ", ".join(f"{k} {v}" for k, v in s["flags"].most_common()))
    return "\n".join(lines)


def write_html(settings: Settings, s: dict) -> str:
    out_path = settings.project_path("cache") / "reports" / "catalogue.html"
    cards = []
    current_day = None
    for r in s["rows"]:
        day = r["day_folder"] or r["trip_folder"] or "(other)"
        if day != current_day:
            if current_day is not None:
                cards.append("</div>")
            cards.append(f"<h2>{html.escape(day)}</h2><div class='grid'>")
            current_day = day
        notes = json.loads(r["notes"] or "[]")
        if r["privacy_class"] == "confidential":
            img = "<div class='conf'>CONFIDENTIAL</div>"
        elif r["thumb_path"]:
            rel = os.path.relpath(settings.project_root / r["thumb_path"], out_path.parent).replace(os.sep, "/")
            img = f"<img loading='lazy' src='{html.escape(rel)}'>"
        else:
            img = "<div class='conf'>no preview</div>"
        dur = f"{r['duration_s']:.1f}s" if r["duration_s"] else ""
        meta = " · ".join(x for x in [
            r["kind"], r["orientation"] or "", f"{r['width']}×{r['height']}" if r["width"] else "", dur,
            _local(r["captured_at"]),
        ] if x)
        badges = "".join(f"<span class='b'>{html.escape(n)}</span>" for n in notes)
        if r["duplicate_of"]:
            badges += "<span class='b warn'>duplicate</span>"
        if r["status"] != "ok":
            badges += f"<span class='b warn'>{html.escape(r['status'])}</span>"
        cards.append(
            f"<figure class='{html.escape(r['privacy_class'])}'>{img}<figcaption><b>{html.escape(r['rel_path'].rsplit('/', 1)[-1])}</b>"
            f"<br>{html.escape(meta)}<br><span class='p'>{html.escape(r['privacy_class'])}</span>{badges}</figcaption></figure>"
        )
    if current_day is not None:
        cards.append("</div>")
    doc = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Media Catalogue</title>
<style>
:root{{--bg:#f6f5f2;--fg:#1d1d1b;--card:#fff;--muted:#6b6a66;--warn:#b54708;--conf:#7a1f1f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe8;--card:#22221f;--muted:#a3a19b;--warn:#f79009;--conf:#f97066}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0;padding:16px}}
h1{{margin:0 0 4px}} pre{{color:var(--muted);white-space:pre-wrap}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
figure{{margin:0;background:var(--card);border-radius:8px;overflow:hidden}}
img{{width:100%;height:220px;object-fit:cover;display:block;background:#0002}}
.conf{{height:220px;display:grid;place-items:center;color:var(--conf);font-weight:700;letter-spacing:.08em}}
figcaption{{padding:8px;font-size:12px;color:var(--muted)}} figcaption b{{color:var(--fg)}}
.b,.p{{display:inline-block;margin:4px 4px 0 0;padding:1px 6px;border-radius:10px;background:#8881;font-size:11px}}
.warn{{color:var(--warn)}} .confidential .p{{color:var(--conf);font-weight:700}}
</style>
<h1>Media Catalogue</h1>
<pre>{html.escape(console_summary(s))}</pre>
{''.join(cards)}
"""
    with open_for_write(settings, out_path) as fh:
        fh.write(doc)
    return str(out_path)
