"""Render an EDL to a draft video with FFmpeg.

Pipeline (all intermediates in cache/tmp/<content_id>/, all outputs via the path guard):
  1. per segment: trim, reframe to the preset canvas (cover = fill and crop,
     fit = blurred background + whole frame), constant 30 fps, yuv420p, 48 kHz
     stereo, short fade at each cut. Photos are EXIF-rotated with Pillow first
     (FFmpeg ignores EXIF orientation) and get a gentle Ken Burns zoom.
  2. concat the segments losslessly
  3. final pass: burn captions (ASS), two-pass loudnorm, H.264 High + AAC,
     all metadata stripped (no GPS, no device info), faststart
  4. write <id>_vN.mp4, a JSON render manifest and an HTML review page to
     05_EDITED_VIDEOS/<Series>/<id>/, and record content/asset rows

Originals are only ever FFmpeg *inputs*. Confidential sources are refused.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings
from app.core.paths import is_raw_media, open_for_write, safe_write_path
from app.core.privacy import classify
from app.media.probe import kind_of, probe

from .edl import EDL

log = logging.getLogger("hq.editor")


class RenderError(RuntimeError):
    pass


@dataclass
class RenderResult:
    video: Path
    review: Path
    manifest: Path
    duration_s: float
    sha256: str
    commands: list[list[str]] = field(default_factory=list)


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RenderError("ffmpeg not found on PATH (install FFmpeg)")
    return exe


def _run(cmd: list[str], log_cmds: list, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    log_cmds.append(cmd)
    log.debug("run: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed: {proc.stderr.strip()[-600:]}")
    return proc


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while b := fh.read(4 * 1024 * 1024):
            h.update(b)
    return h.hexdigest()


def _frame_chain(mode: str, w: int, h: int, focus_x: float) -> str:
    cover = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
             f"crop={w}:{h}:x='(iw-{w})*{focus_x}':y='(ih-{h})/2'")
    if mode == "cover":
        return f"[0:v]{cover},setsar=1[v0]"
    return (f"[0:v]split[a][b];[a]{cover},gblur=sigma=40[bg];"
            f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v0]")


def _blur_boxes_chain(label: str, boxes: list[dict], w: int, h: int) -> tuple[str, str]:
    """Pixelate manual boxes (fractions of the canvas) between from/to seconds. Returns (chain, out label)."""
    chain, cur = "", label
    for n, b in enumerate(boxes):
        bw, bh = max(2, int(b["w"] * w) // 2 * 2), max(2, int(b["h"] * h) // 2 * 2)
        bx, by = int(b["x"] * w), int(b["y"] * h)
        end = f"{b['to']}" if b.get("to") is not None else "1e9"
        chain += (f";[{cur}]split[m{n}a][m{n}b];[m{n}b]crop={bw}:{bh}:{bx}:{by},"
                  f"scale=w=trunc(iw/28)+2:h=trunc(ih/28)+2,scale={bw}:{bh}:flags=neighbor,boxblur=10:2[m{n}c];"
                  f"[m{n}a][m{n}c]overlay={bx}:{by}:enable='between(t,{b['from']},{end})'[mb{n}]")
        cur = f"mb{n}"
    return chain, cur


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _write_ass(path: Path, settings: Settings, w: int, h: int, cues: list[tuple[float, float, str]]) -> None:
    c = settings.render_presets.get("captions", {})
    font, size = c.get("font", "Arial"), int(c.get("size", 64))
    margin, outline = int(c.get("margin_bottom", 420)), int(c.get("outline", 4))
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,"
        f"80,80,{margin},1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in cues:
        safe = text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{{\\fad(150,150)}}{safe}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _next_version(folder: Path, content_id: str) -> int:
    existing = [p.stem for p in folder.glob(f"{content_id}_v*.mp4")] if folder.exists() else []
    nums = [int(s.rsplit("_v", 1)[1]) for s in existing if s.rsplit("_v", 1)[1].isdigit()]
    return max(nums, default=0) + 1


def render(settings: Settings, conn, edl: EDL, *, keep_tmp: bool = False) -> RenderResult:
    presets = settings.render_presets
    if edl.format not in presets:
        raise RenderError(f"No render preset '{edl.format}' in render_presets.yaml")
    p = presets[edl.format]
    W, H, FPS = int(p["width"]), int(p["height"]), int(p.get("fps", 30))
    fade = float(presets.get("segment_fade_s", 0.2))
    photo_s = float(presets.get("photo_default_s", 2.5))
    zoom = float(presets.get("photo_zoom", 1.08))
    cmds: list[list[str]] = []

    # --- validate sources -------------------------------------------------
    sources = []
    for i, seg in enumerate(edl.segments, 1):
        src = settings.media_root / seg.src
        if not src.is_file():
            raise RenderError(f"segment {i}: source not found: {seg.src}")
        if classify(settings, src) == "confidential":
            raise RenderError(f"segment {i}: {seg.src} is confidential and cannot be used in content")
        kind = kind_of(src)
        if kind not in ("video", "photo"):
            raise RenderError(f"segment {i}: unsupported source type: {seg.src}")
        if kind == "video":
            info = probe(src)
            if seg.in_s is not None and info.duration_s and seg.out_s > info.duration_s + 0.05:
                raise RenderError(f"segment {i}: out {seg.out_s}s is past the clip end ({info.duration_s}s)")
        sources.append((seg, src, kind))

    tmp = safe_write_path(settings, settings.project_path("cache") / "tmp" / edl.content_id / "x").parent
    for old in tmp.glob("*"):
        old.unlink()
    ff = _ffmpeg()

    # --- 1. normalised segments ------------------------------------------
    parts, cues, t = [], [], 0.0
    face_hits: dict[int, int] = {}
    for i, (seg, src, kind) in enumerate(sources, 1):
        length = seg.length(photo_s)
        faces_on = edl.blur_faces if seg.blur_faces is None else seg.blur_faces
        out = tmp / f"seg{i:03d}.mkv"
        vfade = (f",fade=t=in:st=0:d={fade},fade=t=out:st={max(length - fade, 0):.3f}:d={fade}" if fade else "")
        if kind == "video":
            inputs = ["-ss", f"{seg.in_s or 0:.3f}", "-i", str(src), "-t", f"{length:.3f}"]
            bchain, blab = _blur_boxes_chain("v0", seg.blur, W, H)
            vchain = (_frame_chain(seg.frame, W, H, seg.focus_x) + bchain
                      + f";[{blab}]fps={FPS},format=yuv420p{vfade}[v]")
            has_audio = probe(src).acodec is not None
        else:
            from PIL import Image, ImageOps

            still = tmp / f"still{i:03d}.png"
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((W * 2, H * 2))
                if faces_on:
                    import numpy as np

                    from app.media.privacy_blur import blur_faces_image

                    arr = np.array(im)[:, :, ::-1].copy()
                    face_hits[i] = blur_faces_image(arr)
                    im = Image.fromarray(arr[:, :, ::-1])
                im.save(still)
            frames = int(round(length * FPS))
            zp = (f"zoompan=z='1+({zoom}-1)*on/{max(frames - 1, 1)}':d=1:"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}")
            inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{length:.3f}", "-i", str(still)]
            if seg.frame == "cover":
                vchain = (f"[0:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
                          f"crop={W * 2}:{H * 2}:x='(iw-{W * 2})*{seg.focus_x}':y='(ih-{H * 2})/2',"
                          f"{zp},setsar=1[v0]")
            else:
                vchain = _frame_chain("fit", W, H, seg.focus_x)
            bchain, blab = _blur_boxes_chain("v0", seg.blur, W, H)
            vchain += bchain + f";[{blab}]fps={FPS},format=yuv420p{vfade}[v]"
            has_audio = False
        if has_audio and edl.audio == "ambient":
            achain = (f";[0:a]aresample=48000,aformat=channel_layouts=stereo,"
                      f"afade=t=in:d={fade or 0.01},afade=t=out:st={max(length - fade, 0):.3f}:d={fade or 0.01}[a]")
            amap = ["-map", "[a]"]
            extra_in = []
        else:
            achain = ""
            extra_in = ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            amap = ["-map", "1:a"]
        cmd = [ff, "-v", "error", "-y", *inputs, *extra_in, "-filter_complex", vchain + achain,
               "-map", "[v]", *amap, "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "16", "-c:a", "pcm_s16le", "-map_metadata", "-1", str(out)]
        _run(cmd, cmds)
        if faces_on and kind == "video":
            from app.media.privacy_blur import blur_faces_video

            blurred = tmp / f"seg{i:03d}_faces.mkv"
            face_hits[i] = blur_faces_video(out, blurred, fps=FPS)
            out.unlink()
            blurred.rename(out)
        parts.append(out)
        if seg.caption:
            cues.append((t + 0.1, t + length - 0.1, seg.caption))
        t += length

    # --- 2. concat --------------------------------------------------------
    listfile = tmp / "concat.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    joined = tmp / "joined.mkv"
    _run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listfile.name, "-c", "copy", joined.name],
         cmds, cwd=tmp)

    # --- 3. final pass ----------------------------------------------------
    folder = settings.media_path("edited") / edl.series / edl.content_id
    version = _next_version(folder, edl.content_id)
    final = safe_write_path(settings, folder / f"{edl.content_id}_v{version}.mp4")
    _write_ass(tmp / "captions.ass", settings, W, H, cues)
    vf = "ass=captions.ass" if cues else "null"

    target = float(presets.get("ambient_lufs", -20)) if edl.audio == "ambient" else float(p["audio"]["loudness_lufs"])
    af = "anull"
    if edl.audio != "mute":
        probe_pass = _run([ff, "-hide_banner", "-y", "-i", joined.name, "-af",
                           f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], cmds, cwd=tmp)
        stats = _parse_loudnorm(probe_pass.stderr)
        if stats and stats.get("input_i") not in (None, "-inf") and float(stats["input_i"]) > -70:
            af = (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={stats['input_i']}:"
                  f"measured_TP={stats['input_tp']}:measured_LRA={stats['input_lra']}:"
                  f"measured_thresh={stats['input_thresh']}:offset={stats['target_offset']}:linear=true,"
                  f"aresample=48000")
    a = p.get("audio", {})
    rate = ["-maxrate", str(p["maxrate"]), "-bufsize", str(p.get("bufsize", "12M"))] if p.get("maxrate") else []
    _run([ff, "-v", "error", "-y", "-i", joined.name, "-vf", vf, "-af", af,
          "-c:v", p.get("vcodec", "libx264"), "-preset", "medium", "-crf", str(p.get("crf", 20)), *rate,
          "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
          "-c:a", a.get("codec", "aac"), "-b:a", a.get("bitrate", "192k"), "-ar", "48000",
          "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", str(final)], cmds, cwd=tmp)

    digest = _sha256(final)
    out_info = probe(final)
    max_s = p.get("max_duration_s")
    warnings = []
    if max_s and out_info.duration_s and out_info.duration_s > max_s:
        warnings.append(f"duration {out_info.duration_s:.1f}s exceeds {edl.format} limit {max_s}s")

    manifest = safe_write_path(settings, folder / f"{edl.content_id}_v{version}.json")
    src_rows = [{"src": s.src, "in": s.in_s, "out": s.out_s, "duration": s.length(photo_s), "frame": s.frame,
                 "focus_x": s.focus_x, "caption": s.caption,
                 "blur_faces": edl.blur_faces if s.blur_faces is None else s.blur_faces,
                 "faces_blurred": face_hits.get(n, 0), "blur_boxes": len(s.blur)}
                for n, (s, _, _) in enumerate(sources, 1)]
    with open_for_write(settings, manifest) as fh:
        json.dump({"content_id": edl.content_id, "version": version, "format": edl.format, "title": edl.title,
                   "video": final.name, "sha256": digest, "duration_s": out_info.duration_s,
                   "width": out_info.width, "height": out_info.height, "loudness_target_lufs": target,
                   "segments": src_rows, "warnings": warnings, "status": "draft - not approved",
                   "ffmpeg": [" ".join(c[1:]) for c in cmds]}, fh, indent=2)

    review = _write_review(settings, edl, folder, version, final, out_info, src_rows, warnings)
    _record(conn, settings, edl, sources, final, digest, version, manifest)

    if not keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return RenderResult(final, review, manifest, out_info.duration_s or 0.0, digest, cmds)


def _parse_loudnorm(stderr: str) -> dict | None:
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(stderr[start:end + 1])
    except json.JSONDecodeError:
        return None


def _write_review(settings, edl, folder, version, final, info, rows, warnings) -> Path:
    path = safe_write_path(settings, folder / f"{edl.content_id}_v{version}_review.html")
    checklist = settings.privacy.get("pre_publish_checklist", [])
    def trim(r):
        return "" if r["in"] is None else f"{r['in']:.1f}–{r['out']:.1f}s"

    shot_rows = "".join(
        f"<tr><td>{i}</td><td>{html.escape(r['src'].rsplit('/', 1)[-1])}</td><td>{trim(r)}</td>"
        f"<td>{r['duration']:.1f}s</td><td>{html.escape(r['frame'])}</td><td>{html.escape(r['caption'] or '')}</td>"
        f"<td>{('faces ' if r['blur_faces'] else '') + (str(r['blur_boxes']) + ' box' if r['blur_boxes'] else '') or '-'}</td></tr>"
        for i, r in enumerate(rows, 1))
    warn = "".join(f"<li>{html.escape(w)}</li>" for w in warnings) or "<li>none</li>"
    checks = "".join(f"<li><label><input type='checkbox'> {html.escape(c)}</label></li>" for c in checklist)
    doc = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(edl.content_id)} v{version} review</title>
<style>
:root{{--bg:#f6f5f2;--fg:#1d1d1b;--card:#fff;--muted:#6b6a66;--accent:#b54708}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe8;--card:#22221f;--muted:#a3a19b;--accent:#f79009}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:16px}}
.wrap{{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start}}
video{{width:min(360px,100%);border-radius:12px;background:#000}}
.card{{background:var(--card);border-radius:10px;padding:14px 16px;flex:1;min-width:280px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{padding:4px 6px;border-bottom:1px solid #8883;text-align:left}}
.status{{color:var(--accent);font-weight:700}} small{{color:var(--muted)}}
</style>
<h1>{html.escape(edl.content_id)} · {html.escape(edl.title)} <small>v{version}</small></h1>
<p class="status">DRAFT, not approved. Nothing is published from this page.</p>
<div class="wrap">
<video src="{html.escape(final.name)}" controls playsinline></video>
<div class="card">
<p>{info.width}×{info.height} · {info.duration_s:.1f}s · {html.escape(edl.format)} · metadata stripped</p>
<h3>Shot list</h3>
<table><tr><th>#</th><th>Source</th><th>Trim</th><th>Length</th><th>Frame</th><th>Caption</th><th>Blur</th></tr>{shot_rows}</table>
<h3>Warnings</h3><ul>{warn}</ul>
<h3>Before approving</h3><ul style="list-style:none;padding:0">{checks}</ul>
<p><small>To change the cut, edit <code>02_SELECTED_FOOTAGE/{html.escape(edl.series)}/{html.escape(edl.content_id)}/edl.yaml</code>
and run <code>hq render</code> again; a new version is created, this one is kept.</small></p>
</div></div>
"""
    with open_for_write(settings, path) as fh:
        fh.write(doc)
    return path


def _record(conn, settings, edl, sources, final, digest, version, manifest) -> None:
    series_code = next((s["code"] for s in settings.settings.get("series", []) if s.get("name") == edl.series), edl.series)
    conn.execute(
        "INSERT INTO content (id, series, format, title, state) VALUES (?,?,?,?, 'rough_cut') "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, state='rough_cut'",
        (edl.content_id, series_code, edl.format, edl.title))
    conn.execute("DELETE FROM content_media WHERE content_id=?", (edl.content_id,))
    for pos, (seg, src, kind) in enumerate(sources, 1):
        rel = src.resolve().relative_to(settings.media_root).as_posix()
        row = conn.execute("SELECT id FROM media WHERE rel_path=?", (rel,)).fetchone()
        if row:
            conn.execute("INSERT INTO content_media (content_id, media_id, position, in_s, out_s, role) "
                         "VALUES (?,?,?,?,?,?)", (edl.content_id, row["id"], pos, seg.in_s, seg.out_s,
                                                  "still" if kind == "photo" else "a-roll"))
    conn.execute("INSERT INTO assets (content_id, kind, path, sha256, version, recipe_json) VALUES (?,?,?,?,?,?)",
                 (edl.content_id, "video", final.relative_to(settings.media_root).as_posix(), digest, version,
                  json.dumps({"manifest": manifest.name})))
    conn.execute("INSERT INTO events (entity, entity_id, to_state, actor, note) VALUES ('content', ?, 'rough_cut', "
                 "'video_editor', ?)", (edl.content_id, f"rendered v{version}"))
    conn.commit()
