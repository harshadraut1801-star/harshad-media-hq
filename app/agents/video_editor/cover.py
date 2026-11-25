"""Reel cover / YouTube thumbnail maker. Free and local (OpenCV + Pillow).

Two steps, both from a *rendered* video, so plate boxes and face blur that the
render applied are already in every frame:

1. ``candidates()`` samples the video, scores each frame (sharpness, exposure,
   colour, faces, no burned-in caption), keeps the best frames that are spread
   out in time and look different, and writes them as JPEGs plus a
   ``candidates.html`` contact sheet to ``06_THUMBNAILS/<Series>/<id>/candidates/``.
2. ``make_cover()`` takes one frame time and a title (Harsh's words, never
   invented) and writes ``cover_vN.jpg`` and ``thumbnail.jpg`` to
   ``06_THUMBNAILS/<Series>/<id>/``, plus ``grid_preview.jpg`` showing how
   Instagram's 3:4 profile grid crops it. ``thumbnail.jpg`` is what the
   approval package picks up.

All outputs are written with no EXIF or other metadata. Confidential content is
refused.
"""
from __future__ import annotations

import base64
import html
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.paths import open_for_write, safe_write_path

log = logging.getLogger("hq.cover")

SIZES = {"reel": (1080, 1920), "short": (1080, 1920), "long": (1280, 720)}
DEFAULT_FONTS = ["arialbd.ttf", "Arial Bold.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]


class CoverError(RuntimeError):
    pass


@dataclass
class Candidate:
    t: float
    score: float
    sharpness: float
    brightness: float
    colourfulness: float
    faces: int
    caption_on_screen: bool
    file: str = ""


# ---------- helpers ----------

def _manifest(video: Path) -> dict:
    m = video.with_suffix(".json")
    if m.is_file():
        try:
            return json.loads(m.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("manifest unreadable: %s", m)
    return {}


def caption_windows(manifest: dict) -> list[tuple[float, float]]:
    """(start, end) seconds where a burned-in caption is on screen."""
    out, t = [], 0.0
    for seg in manifest.get("segments", []):
        d = float(seg.get("duration") or 0)
        if seg.get("caption"):
            out.append((t, t + d))
        t += d
    return out


def _thumb_folder(settings: Settings, series: str, content_id: str) -> Path:
    return settings.media_path("thumbnails") / series / content_id


def _refuse_confidential(conn, content_id: str) -> None:
    if conn is None:
        return
    rows = conn.execute("SELECT m.rel_path FROM content_media cm JOIN media m ON m.id=cm.media_id "
                        "WHERE cm.content_id=? AND m.privacy_class='confidential'", (content_id,)).fetchall()
    if rows:
        raise CoverError(f"{content_id} uses confidential media; no cover will be made: {[r[0] for r in rows]}")


def _score(frame, det) -> tuple[float, float, float, int]:
    import cv2
    import numpy as np

    small = cv2.resize(frame, (360, int(360 * frame.shape[0] / frame.shape[1])))
    grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(grey, cv2.CV_64F).var())
    bright = float(grey.mean()) / 255.0
    b, g, r = [c.astype(np.float32) for c in cv2.split(small)]
    rg, yb = np.abs(r - g), np.abs(0.5 * (r + g) - b)
    colour = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    faces = len(det.detect(frame)) if det is not None else 0
    return sharp, bright, colour, faces


def _combine(sharp: float, bright: float, colour: float, faces: int, captioned: bool) -> float:
    import math

    s = min(math.log1p(sharp) / math.log1p(1500), 1.0)          # 0..1, saturates on crisp frames
    e = max(0.0, 1.0 - abs(bright - 0.5) / 0.35)                 # best near mid exposure, 0 if very dark/bright
    c = min(colour / 90.0, 1.0)
    score = 0.45 * s + 0.30 * e + 0.25 * c + (0.08 if faces else 0.0) - (0.15 if captioned else 0.0)
    return round(max(score, 0.0) * 100, 1)


def _hist(frame):
    import cv2

    hsv = cv2.cvtColor(cv2.resize(frame, (160, 284)), cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


# ---------- step 1: candidates ----------

def candidates(settings: Settings, video: Path, series: str, content_id: str, *, n: int = 12,
               every_s: float = 0.25, conn=None, use_faces: bool = True) -> tuple[Path, list[Candidate]]:
    import cv2

    _refuse_confidential(conn, content_id)
    det = None
    if use_faces:
        try:
            from app.media.privacy_blur import FaceDetector
            det = FaceDetector()
        except Exception as exc:  # model missing etc.: scoring still works without the face bonus
            log.warning("face detector unavailable, scoring without faces: %s", exc)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise CoverError(f"Cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps * every_s)))
    windows = caption_windows(_manifest(video))
    pool, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            t = idx / fps
            sharp, bright, colour, faces = _score(frame, det)
            captioned = any(a <= t < b for a, b in windows)
            c = Candidate(round(t, 2), _combine(sharp, bright, colour, faces, captioned), round(sharp, 1),
                          round(bright, 3), round(colour, 1), faces, captioned)
            pool.append((c, frame, _hist(frame)))
        idx += 1
    cap.release()
    if not pool:
        raise CoverError(f"No frames read from {video}")

    duration = idx / fps
    min_gap = max(0.5, duration / (n * 2.0))
    chosen: list[tuple[Candidate, object, object]] = []
    for c, frame, h in sorted(pool, key=lambda p: p[0].score, reverse=True):
        if len(chosen) >= n:
            break
        if any(abs(c.t - o.t) < min_gap for o, _, _ in chosen):
            continue
        if any(cv2.compareHist(h, oh, cv2.HISTCMP_CORREL) > 0.97 for _, _, oh in chosen):
            continue
        chosen.append((c, frame, h))
    chosen.sort(key=lambda p: p[0].score, reverse=True)

    folder = _thumb_folder(settings, series, content_id) / "candidates"
    tiles = []
    for rank, (c, frame, _) in enumerate(chosen, 1):
        name = f"{rank:02d}_t{c.t:06.2f}.jpg"
        path = safe_write_path(settings, folder / name)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])   # cv2 writes no EXIF
        path.write_bytes(jpg.tobytes())
        c.file = name
        small = cv2.resize(frame, (270, int(270 * frame.shape[0] / frame.shape[1])))
        tiles.append((c, base64.b64encode(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])[1]).decode()))
    report = _write_sheet(settings, folder, video, content_id, tiles)
    with open_for_write(settings, folder / "candidates.json") as fh:
        json.dump({"video": video.name, "content_id": content_id, "candidates": [asdict(c) for c, _ in tiles]},
                  fh, indent=2)
    return report, [c for c, _ in tiles]


def _write_sheet(settings, folder: Path, video: Path, content_id: str, tiles) -> Path:
    cards = "\n".join(
        f'<figure><img src="data:image/jpeg;base64,{b64}"><figcaption><b>#{i}</b> at {c.t:.2f}s · score {c.score}'
        f'{" · faces " + str(c.faces) if c.faces else ""}{" · caption on screen" if c.caption_on_screen else ""}'
        f'<br><code>hq cover {html.escape(content_id)} --t {c.t:.2f} --title "..."</code></figcaption></figure>'
        for i, (c, b64) in enumerate(tiles, 1))
    doc = f"""<!doctype html><meta charset="utf-8"><title>{html.escape(content_id)} cover candidates</title>
<style>body{{font:14px system-ui,sans-serif;margin:16px;background:#111;color:#eee}}
.grid{{display:flex;flex-wrap:wrap;gap:12px}}figure{{margin:0;width:270px}}img{{width:270px;border-radius:6px}}
code{{font-size:11px;color:#9cf;word-break:break-all}}</style>
<h1>{html.escape(content_id)}: cover candidates from {html.escape(video.name)}</h1>
<p>Best first. Scored on sharpness, exposure, colour and faces; frames with a burned-in caption score lower.
Pick one and run the command under it with your own title. Check it for plates and faces before using it.</p>
<div class="grid">{cards}</div>"""
    path = safe_write_path(settings, folder / "candidates.html")
    path.write_text(doc, encoding="utf-8")
    return path


# ---------- step 2: compose ----------

def _font(settings: Settings, size: int):
    from PIL import ImageFont

    cfg = (settings.render_presets or {}).get("cover", {})
    names = ([cfg["font"]] if cfg.get("font") else []) + DEFAULT_FONTS
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise CoverError(f"No bold font found (tried {names}). Set cover.font in config/render_presets.yaml.")


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return [ln for ln in lines if ln]


def grab_frame(video: Path, t: float):
    import cv2
    from PIL import Image

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    target = int(round(t * fps))
    if total and target >= total:
        cap.release()
        raise CoverError(f"t={t}s is past the end of {video.name} ({total / fps:.2f}s)")
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise CoverError(f"Could not read a frame at {t}s from {video.name}")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def _fit(img, size):
    from PIL import Image, ImageOps

    return ImageOps.fit(img, size, method=Image.LANCZOS, centering=(0.5, 0.5))


def compose(settings: Settings, frame, title: str, subtitle: str | None, fmt: str):
    """Frame + title. Text sits in the upper part of the 3:4 centre band so the
    Instagram profile grid crop keeps it, with a soft dark gradient behind it."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = SIZES[fmt]
    img = _fit(frame.convert("RGB"), (w, h))
    portrait = h > w
    safe_top = (h - int(w * 4 / 3)) // 2 if portrait else int(h * 0.06)     # top of the 3:4 grid crop
    max_w = int(w * 0.84)
    size = int(w * (0.105 if portrait else 0.085))
    draw = ImageDraw.Draw(img)
    font = _font(settings, size)
    lines = _wrap(draw, title, font, max_w)
    while len(lines) > 3 and size > 40:
        size = int(size * 0.88)
        font = _font(settings, size)
        lines = _wrap(draw, title, font, max_w)
    sub_font = _font(settings, int(size * 0.5)) if subtitle else None
    line_h = int(size * 1.15)
    block_h = line_h * len(lines) + (int(size * 0.75) if subtitle else 0)
    y0 = safe_top + int(size * 0.6)

    shade = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(shade)
    fade_h = int(size * 2.5)
    solid_end = y0 + block_h + int(size * 0.3)
    for y in range(0, min(h, solid_end + fade_h)):
        a = 120 if y < solid_end else int(120 * (1 - (y - solid_end) / fade_h) ** 2)
        sd.line([(0, y), (w, y)], fill=max(a, 0))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, shade.filter(ImageFilter.GaussianBlur(8)))
    draw = ImageDraw.Draw(img)
    stroke = max(3, size // 14)
    y = y0
    for ln in lines:
        x = (w - draw.textlength(ln, font=font)) / 2
        draw.text((x, y), ln, font=font, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h
    if subtitle:
        x = (w - draw.textlength(subtitle, font=sub_font)) / 2
        draw.text((x, y + int(size * 0.1)), subtitle, font=sub_font, fill=(255, 214, 90),
                  stroke_width=max(2, stroke // 2), stroke_fill=(0, 0, 0))
    return img


def grid_preview(img):
    """What the Instagram profile grid shows: centre 3:4 crop."""
    w, h = img.size
    gh = int(w * 4 / 3)
    if gh >= h:
        return img.copy()
    top = (h - gh) // 2
    return img.crop((0, top, w, top + gh))


def _save_clean(settings: Settings, img, path: Path) -> Path:
    path = safe_write_path(settings, path)
    clean = img.convert("RGB")
    clean.info.clear()
    clean.save(path, "JPEG", quality=92, optimize=True)       # no exif= given, so no metadata is written
    return path


def _next_cover_version(folder: Path) -> int:
    nums = [int(p.stem.split("_v")[1]) for p in folder.glob("cover_v*.jpg") if p.stem.split("_v")[1].isdigit()]
    return max(nums, default=0) + 1


@dataclass
class CoverResult:
    cover: Path
    thumbnail: Path
    grid_preview: Path
    version: int
    sha256: str


def make_cover(settings: Settings, video: Path, series: str, content_id: str, *, t: float, title: str,
               subtitle: str | None = None, fmt: str = "reel", conn=None, series_code: str | None = None) -> CoverResult:
    import hashlib

    if not title or not title.strip():
        raise CoverError("A title is required (your words; nothing is made up).")
    if fmt not in SIZES:
        raise CoverError(f"Unknown format {fmt!r}; use one of {sorted(SIZES)}")
    _refuse_confidential(conn, content_id)
    frame = grab_frame(video, t)
    img = compose(settings, frame, title.strip(), subtitle, fmt)
    folder = _thumb_folder(settings, series, content_id)
    version = _next_cover_version(folder) if folder.exists() else 1
    cover = _save_clean(settings, img, folder / f"cover_v{version}.jpg")
    thumb = _save_clean(settings, img, folder / "thumbnail.jpg")
    grid = _save_clean(settings, grid_preview(img), folder / "grid_preview.jpg")
    digest = hashlib.sha256(thumb.read_bytes()).hexdigest()
    recipe = {"video": video.name, "t": t, "title": title.strip(), "subtitle": subtitle, "format": fmt,
              "cover": cover.name}
    with open_for_write(settings, folder / f"cover_v{version}.json") as fh:
        json.dump(recipe | {"sha256": digest}, fh, indent=2)
    if conn is not None:
        if conn.execute("SELECT 1 FROM content WHERE id=?", (content_id,)).fetchone():
            conn.execute("INSERT INTO assets (content_id, kind, path, sha256, version, recipe_json) "
                         "VALUES (?,?,?,?,?,?)",
                         (content_id, "thumbnail", thumb.relative_to(settings.media_root).as_posix(), digest,
                          version, json.dumps(recipe)))
            conn.execute("INSERT INTO events (entity, entity_id, actor, note) VALUES ('content', ?, "
                         "'video_editor', ?)", (content_id, f"cover v{version} from {video.name} at {t}s"))
            conn.commit()
    return CoverResult(cover, thumb, grid, version, digest)
