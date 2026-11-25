"""Thumbnails and low-res proxies, written to cache/ via the path guard.

Originals are opened read-only. Outputs strip all metadata (GPS, device).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.core.config import Settings
from app.core.paths import safe_write_path

log = logging.getLogger("hq.media")


def _run(cmd: list[str], timeout: int) -> None:
    log.debug("run: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-300:]}")


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (install FFmpeg)")
    return exe


def video_thumbnail(settings: Settings, src: Path, key: str, duration_s: float | None, width: int = 360) -> Path:
    out = safe_write_path(settings, settings.project_path("cache") / "thumbs" / f"{key}.jpg")
    at = min(1.0, (duration_s or 0) / 2)
    _run([_ffmpeg(), "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
          "-vf", f"scale={width}:-2", "-map_metadata", "-1", str(out)], timeout=120)
    return out


def photo_thumbnail(settings: Settings, src: Path, key: str, width: int = 360) -> Path:
    from PIL import Image, ImageOps

    out = safe_write_path(settings, settings.project_path("cache") / "thumbs" / f"{key}.jpg")
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((width, width * 3))
        im.convert("RGB").save(out, "JPEG", quality=80)  # no exif passed, so metadata is dropped
    return out


def video_proxy(settings: Settings, src: Path, key: str, short_side: int = 540) -> Path:
    """H.264 CFR 30 fps proxy for fast preview and frame sampling. Rotation is applied."""
    out = safe_write_path(settings, settings.project_path("cache") / "proxies" / f"{key}.mp4")
    vf = f"scale='if(gt(iw,ih),-2,{short_side})':'if(gt(iw,ih),{short_side},-2)',fps=30"
    _run([_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "28", "-c:a", "aac", "-b:a", "96k", "-map_metadata", "-1", "-movflags", "+faststart", str(out)],
         timeout=1800)
    return out
