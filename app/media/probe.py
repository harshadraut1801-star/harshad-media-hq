"""Read technical metadata from videos (ffprobe) and photos (Pillow EXIF).

Read-only. Handles S21 FE quirks seen on real Day 01 footage:
- portrait video stored as 2336x1080 or 1920x1080 with display-matrix rotation -90
- photos stored 4000x1848 with EXIF Orientation 6 (rotate 90)
- variable frame rate (avg_frame_rate differs from r_frame_rate)
- creation_time in UTC; filenames are local time (IST)
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

log = logging.getLogger("hq.media")

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".mkv"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".dng"}
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".ogg"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


class ProbeError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    kind: str
    width: int | None = None            # display width (after rotation)
    height: int | None = None
    rotation: int = 0
    orientation: str | None = None
    duration_s: float | None = None
    fps: float | None = None
    vfr: bool = False
    vcodec: str | None = None
    acodec: str | None = None
    hdr: bool = False
    captured_at: str | None = None      # ISO 8601
    gps_lat: float | None = None
    gps_lon: float | None = None
    camera_model: str | None = None
    motion_photo: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in PHOTO_EXT:
        return "photo"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in ARCHIVE_EXT:
        return "archive"
    return "other"


def orientation_of(w: int | None, h: int | None) -> str | None:
    if not w or not h:
        return None
    if abs(w - h) / max(w, h) < 0.02:
        return "square"
    return "portrait" if h > w else "landscape"


def _ffprobe(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise ProbeError("ffprobe not found on PATH (install FFmpeg)")
    cmd = [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    log.debug("run: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise ProbeError(f"ffprobe failed on {path.name}: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout or "{}")


def _rate(s: str | None) -> float | None:
    try:
        f = Fraction(s)  # type: ignore[arg-type]
        return float(f) if f else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            return int(round(float(sd["rotation"])))
    tag = (stream.get("tags") or {}).get("rotate")
    return int(tag) if tag else 0


def parse_iso6709(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    m = _ISO6709.match(value.strip())
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def probe_video(path: Path) -> MediaInfo:
    data = _ffprobe(path)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    info = MediaInfo(kind="video")
    if v is None:
        info.notes.append("no_video_stream")
    else:
        rot = _rotation(v)
        w, h = v.get("width"), v.get("height")
        if abs(rot) % 180 == 90:
            w, h = h, w
        info.width, info.height, info.rotation = w, h, rot
        info.orientation = orientation_of(w, h)
        info.vcodec = v.get("codec_name")
        nominal, avg = _rate(v.get("r_frame_rate")), _rate(v.get("avg_frame_rate"))
        capture = _rate(tags.get("com.android.capture.fps"))
        info.fps = round(capture or avg or nominal or 0, 3) or None
        if avg and (nominal is None or abs(avg - nominal) / max(avg, 1) > 0.01 or nominal > 240):
            info.vfr = True
        info.hdr = v.get("color_transfer") in HDR_TRANSFERS
    if a is not None:
        info.acodec = a.get("codec_name")
    else:
        info.notes.append("no_audio")
    try:
        info.duration_s = round(float(fmt.get("duration")), 3)
    except (TypeError, ValueError):
        pass
    info.captured_at = _normalise_time(tags.get("creation_time"))
    info.gps_lat, info.gps_lon = parse_iso6709(tags.get("location") or tags.get("com.apple.quicktime.location.iso6709"))
    info.camera_model = tags.get("com.android.manufacturer") or tags.get("model")
    return info


def _normalise_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _gps_decimal(dms, ref) -> float | None:
    try:
        d, m, s = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    val = d + m / 60 + s / 3600
    return -val if ref in ("S", "W") else val


def probe_photo(path: Path, tz_offset_minutes: int = 330) -> MediaInfo:
    """EXIF DateTimeOriginal has no zone; phone local time (IST, +330 min) is assumed."""
    from PIL import ExifTags, Image, UnidentifiedImageError

    info = MediaInfo(kind="photo")
    try:
        with Image.open(path) as im:
            w, h = im.size
            exif = im.getexif()
    except (UnidentifiedImageError, OSError):
        info.notes.append("unreadable_by_pillow")
        try:
            data = _ffprobe(path)
            s = data.get("streams", [{}])[0]
            info.width, info.height = s.get("width"), s.get("height")
            info.orientation = orientation_of(info.width, info.height)
        except ProbeError:
            pass
        return info

    named = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
    exif_ifd = exif.get_ifd(0x8769)
    named.update({ExifTags.TAGS.get(k, k): v for k, v in exif_ifd.items()})
    orient = int(named.get("Orientation", 1) or 1)
    rot = {3: 180, 6: 90, 8: 270}.get(orient, 0)
    if rot in (90, 270):
        w, h = h, w
    info.width, info.height, info.rotation = w, h, rot
    info.orientation = orientation_of(w, h)
    info.camera_model = named.get("Model")
    raw_dt = named.get("DateTimeOriginal") or named.get("DateTime")
    if raw_dt:
        try:
            from datetime import timedelta

            local = datetime.strptime(str(raw_dt).strip(), "%Y:%m:%d %H:%M:%S")
            utc = local - timedelta(minutes=tz_offset_minutes)
            info.captured_at = utc.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            pass
    gps = exif.get_ifd(0x8825)
    if gps:
        info.gps_lat = _gps_decimal(gps.get(2), gps.get(1))
        info.gps_lon = _gps_decimal(gps.get(4), gps.get(3))
    info.motion_photo = _is_motion_photo(path)
    return info


def _is_motion_photo(path: Path) -> bool:
    """Samsung Motion Photo: MP4 appended after the JPEG, marked 'MotionPhoto_Data' / ftyp box."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - 8 * 1024 * 1024))
        tail = fh.read()
    return b"MotionPhoto_Data" in tail or b"ftypmp4" in tail or b"ftypisom" in tail


def probe(path: Path) -> MediaInfo:
    kind = kind_of(path)
    if kind == "video":
        return probe_video(path)
    if kind == "photo":
        return probe_photo(path)
    if kind == "audio":
        data = _ffprobe(path)
        info = MediaInfo(kind="audio")
        try:
            info.duration_s = round(float(data.get("format", {}).get("duration")), 3)
        except (TypeError, ValueError):
            pass
        return info
    return MediaInfo(kind="other")
