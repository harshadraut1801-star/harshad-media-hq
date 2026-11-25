"""Synthetic test media shaped like S21 FE output. Never real family media."""
from __future__ import annotations

import subprocess
from pathlib import Path


def make_video(path: Path, *, w=320, h=180, seconds=2.0, rotation=0, location=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30",
           "-f", "lavfi", "-i", "sine=f=440", "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-metadata", "creation_time=2026-11-25T07:18:37Z"]
    if location:
        cmd += ["-metadata", f"location={location}"]
    subprocess.run(cmd + [str(tmp)], check=True)
    if rotation:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", str(rotation), "-i", str(tmp),
                        "-c", "copy", "-map_metadata", "0",
                        "-metadata", "creation_time=2026-11-25T07:18:37Z", str(path)], check=True)
        tmp.unlink()
    else:
        tmp.rename(path)
    return path


def make_photo(path: Path, *, w=400, h=185, orientation=6, gps=None) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (w, h), (120, 160, 200))
    exif = Image.Exif()
    exif[0x0112] = orientation          # Orientation
    exif[0x0110] = "SM-G990E"           # Model
    exif[0x0132] = "2026:11:25 14:14:56"
    if gps:
        lat, lon = gps
        def dms(x):
            x = abs(x); d = int(x); m = int((x - d) * 60); s = round(((x - d) * 60 - m) * 60, 2)
            return (d, m, s)
        exif[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lon >= 0 else "W", 4: dms(lon)}
    im.save(path, "JPEG", exif=exif)
    return path
