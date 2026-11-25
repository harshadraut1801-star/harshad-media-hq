import json
import subprocess

import pytest
import yaml

from app.agents.video_editor import load_edl, render
from app.agents.video_editor.edl import EDLError
from app.agents.video_editor.render import RenderError
from app.db import connect, migrate
from tests.media_factory import make_photo, make_video

DAY1 = "01_RAW_MEDIA/Jaipur Diaries/Day 01 - Aurangabad to Indore"
FNEI = "01_RAW_MEDIA/Jaipur Diaries/Customer Visit - FNEI"


@pytest.fixture()
def env(settings):
    # tiny canvas keeps the test fast; pipeline is identical
    settings.render_presets["reel"].update(width=108, height=192)
    settings.render_presets["captions"]["size"] = 8
    settings.render_presets["captions"]["margin_bottom"] = 20
    root = settings.media_root
    make_video(root / DAY1 / "a.mp4", w=320, h=180, seconds=3, rotation=-90, location="+19.8762+075.3433/")
    make_video(root / DAY1 / "b.mp4", w=320, h=180, seconds=3)
    make_photo(root / DAY1 / "p.jpg", gps=(19.88, 75.34))
    make_video(root / FNEI / "secret.mp4", seconds=1)
    conn = connect(settings)
    migrate(settings, conn)
    return settings, conn


def _edl(settings, segments, name="edl.yaml", **extra):
    folder = settings.media_root / "02_SELECTED_FOOTAGE" / "Jaipur Diaries" / "JD-R-001"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"content_id": "JD-R-001", "series": "Jaipur Diaries", "format": "reel", "title": "Test",
            "segments": segments, **extra}
    path = folder / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return load_edl(path)


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_render_reel_end_to_end(env):
    settings, conn = env
    raw_before = {p: p.stat().st_mtime_ns for p in settings.raw_media.rglob("*") if p.is_file()}
    edl = _edl(settings, [
        {"src": f"{DAY1}/a.mp4", "in": 0.5, "out": 2.0, "caption": "Day 01"},
        {"src": f"{DAY1}/b.mp4", "in": 0, "out": 1.5, "frame": "fit"},
        {"src": f"{DAY1}/p.jpg", "duration": 1.0, "caption": "Breakfast first"},
    ])
    res = render(settings, conn, edl)
    assert res.video.name == "JD-R-001_v1.mp4"
    assert res.duration_s == pytest.approx(4.0, abs=0.15)
    info = _probe(res.video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["r_frame_rate"]) == (108, 192, "30/1")
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    tags = {k.lower() for k in info["format"].get("tags", {})}
    assert "location" not in tags and "creation_time" not in tags     # metadata stripped
    assert res.review.is_file() and "DRAFT" in res.review.read_text(encoding="utf-8")
    assert json.loads(res.manifest.read_text())["sha256"] == res.sha256
    assert {p: p.stat().st_mtime_ns for p in settings.raw_media.rglob("*") if p.is_file()} == raw_before
    assert conn.execute("SELECT state FROM content WHERE id='JD-R-001'").fetchone()[0] == "rough_cut"
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE kind='video'").fetchone()[0] == 1
    assert not (settings.project_path("cache") / "tmp" / "JD-R-001").exists()


def test_rerender_makes_new_version(env):
    settings, conn = env
    edl = _edl(settings, [{"src": f"{DAY1}/b.mp4", "in": 0, "out": 1.0}], audio="mute")
    assert render(settings, conn, edl).video.name == "JD-R-001_v1.mp4"
    assert render(settings, conn, edl).video.name == "JD-R-001_v2.mp4"


def test_confidential_source_refused(env):
    settings, conn = env
    edl = _edl(settings, [{"src": f"{FNEI}/secret.mp4", "in": 0, "out": 0.5}])
    with pytest.raises(RenderError, match="confidential"):
        render(settings, conn, edl)


def test_trim_past_end_refused(env):
    settings, conn = env
    edl = _edl(settings, [{"src": f"{DAY1}/b.mp4", "in": 1, "out": 9}])
    with pytest.raises(RenderError, match="past the clip end"):
        render(settings, conn, edl)


@pytest.mark.parametrize("seg,msg", [
    ({"src": "x.mp4", "in": 2, "out": 1}, "after"),
    ({"src": "x.mp4", "in": 1}, "both"),
    ({"src": "x.mp4", "frame": "stretch"}, "frame"),
    ({"in": 0, "out": 1}, "src"),
])
def test_edl_validation(settings, seg, msg):
    with pytest.raises(EDLError, match=msg):
        _edl(settings, [seg])
