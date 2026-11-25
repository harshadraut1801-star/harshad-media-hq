"""Edit decision list (EDL): the human-editable recipe for one piece of content.

Lives at 02_SELECTED_FOOTAGE/<Series>/<content_id>/edl.yaml. Example:

    content_id: JD-R-001
    series: Jaipur Diaries
    format: reel                  # reel | short | long (render_presets.yaml)
    title: "Day 01: Aurangabad to Indore"
    audio: ambient                # ambient (clip sound) | mute
    segments:
      - src: 01_RAW_MEDIA/Jaipur Diaries/Day 01 - Aurangabad to Indore/20261125_124826.mp4
        in: 0.5                   # seconds into the clip
        out: 4.5
        frame: cover              # cover (fill, crop) | fit (blur-pad) ; landscape->9:16
        focus_x: 0.5              # 0 = keep left edge, 1 = right edge, when cropping
        caption: "Day 01"
      - src: .../20261125_093306.jpg
        duration: 2.5             # photos only
        caption: "Breakfast stop"

Paths are relative to MEDIA_ROOT. The EDL never points at a confidential file;
the renderer refuses it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRAMES = ("cover", "fit")


class EDLError(ValueError):
    pass


@dataclass
class Segment:
    src: str
    in_s: float | None = None
    out_s: float | None = None
    duration: float | None = None
    frame: str = "cover"
    focus_x: float = 0.5
    caption: str | None = None

    def length(self, default_photo_s: float) -> float:
        if self.in_s is not None and self.out_s is not None:
            return self.out_s - self.in_s
        return self.duration or default_photo_s


@dataclass
class EDL:
    content_id: str
    series: str
    format: str
    title: str = ""
    audio: str = "ambient"
    segments: list[Segment] = field(default_factory=list)
    path: Path | None = None


def load_edl(path: Path | str) -> EDL:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("content_id", "series", "format", "segments"):
        if key not in data:
            raise EDLError(f"{path.name}: missing '{key}'")
    if data.get("audio", "ambient") not in ("ambient", "mute"):
        raise EDLError("audio must be 'ambient' or 'mute'")
    segs = []
    for i, s in enumerate(data["segments"], 1):
        if "src" not in s:
            raise EDLError(f"segment {i}: missing 'src'")
        seg = Segment(
            src=str(s["src"]),
            in_s=_num(s.get("in")),
            out_s=_num(s.get("out")),
            duration=_num(s.get("duration")),
            frame=s.get("frame", "cover"),
            focus_x=float(s.get("focus_x", 0.5)),
            caption=s.get("caption"),
        )
        if seg.frame not in FRAMES:
            raise EDLError(f"segment {i}: frame must be one of {FRAMES}")
        if not 0 <= seg.focus_x <= 1:
            raise EDLError(f"segment {i}: focus_x must be 0..1")
        if (seg.in_s is None) != (seg.out_s is None):
            raise EDLError(f"segment {i}: give both 'in' and 'out', or neither")
        if seg.in_s is not None and seg.out_s <= seg.in_s:
            raise EDLError(f"segment {i}: 'out' must be after 'in'")
        segs.append(seg)
    if not segs:
        raise EDLError("EDL has no segments")
    return EDL(content_id=data["content_id"], series=data["series"], format=data["format"],
               title=data.get("title", ""), audio=data.get("audio", "ambient"), segments=segs, path=path)


def _num(v) -> float | None:
    return None if v is None else float(v)
