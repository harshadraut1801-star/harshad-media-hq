import subprocess

import numpy as np
import pytest
import yaml

from app.agents.video_editor import load_edl, render
from app.agents.video_editor.edl import EDLError
from app.db import connect, migrate
from app.media import privacy_blur
from tests.media_factory import make_photo, make_video

DAY1 = "01_RAW_MEDIA/Jaipur Diaries/Day 01 - Aurangabad to Indore"


def _frame(path, t=0.5):
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return out


def _edl(settings, segments, **extra):
    folder = settings.media_root / "02_SELECTED_FOOTAGE" / "Jaipur Diaries" / "JD-R-009"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "edl.yaml"
    path.write_text(yaml.safe_dump({"content_id": "JD-R-009", "series": "Jaipur Diaries", "format": "reel",
                                    "segments": segments, **extra}), encoding="utf-8")
    return load_edl(path)


@pytest.fixture()
def env(settings):
    settings.render_presets["reel"].update(width=216, height=384)
    settings.render_presets["segment_fade_s"] = 0
    make_video(settings.media_root / DAY1 / "a.mp4", w=384, h=216, seconds=2, rotation=-90)
    make_photo(settings.media_root / DAY1 / "p.jpg", w=800, h=400)
    conn = connect(settings)
    migrate(settings, conn)
    return settings, conn


def test_model_present_and_detector_loads():
    assert privacy_blur.MODEL.is_file()
    det = privacy_blur.FaceDetector()
    assert det.detect(np.zeros((480, 640, 3), np.uint8)) == []


def test_pixelate_changes_only_the_box():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    before = img.copy()
    privacy_blur.pixelate(img, (50, 60, 40, 30))
    assert not np.array_equal(img[60:90, 50:90], before[60:90, 50:90])
    img[60:90, 50:90] = before[60:90, 50:90]
    assert np.array_equal(img, before)


def test_grow_stays_inside_image():
    assert privacy_blur.grow((0, 0, 100, 100), 120, 120) == (0, 0, 117, 117)


def test_manual_blur_box_changes_region(env):
    settings, conn = env
    seg = {"src": f"{DAY1}/a.mp4", "in": 0, "out": 1.5}
    plain = render(settings, conn, _edl(settings, [seg], audio="mute")).video
    boxed = render(settings, conn, _edl(settings, [{**seg, "blur": [{"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.25}]}],
                                       audio="mute")).video
    W, H = 216, 384
    a = np.frombuffer(_frame(plain), np.uint8).reshape(H, W)
    b = np.frombuffer(_frame(boxed), np.uint8).reshape(H, W)
    inside = (slice(int(H * 0.3), int(H * 0.45)), slice(int(W * 0.3), int(W * 0.7)))
    outside = (slice(int(H * 0.7), H), slice(0, W))
    assert np.abs(a[inside].astype(int) - b[inside]).mean() > 3       # blurred
    assert np.abs(a[outside].astype(int) - b[outside]).mean() < 2     # untouched


def test_blur_faces_runs_detector_on_video_and_photo(env, monkeypatch):
    settings, conn = env
    calls = {"n": 0}

    def fake_detect(self, bgr):
        calls["n"] += 1
        h, w = bgr.shape[:2]
        return [(w // 4, h // 4, w // 4, h // 4, 0.99)]

    monkeypatch.setattr(privacy_blur.FaceDetector, "detect", fake_detect)
    res = render(settings, conn, _edl(settings, [{"src": f"{DAY1}/a.mp4", "in": 0, "out": 1.0},
                                                  {"src": f"{DAY1}/p.jpg", "duration": 1.0}],
                                      audio="mute", blur_faces=True))
    import json
    segs = json.loads(res.manifest.read_text())["segments"]
    assert segs[0]["faces_blurred"] >= 25 and segs[1]["faces_blurred"] == 1
    assert calls["n"] >= 31


def test_segment_can_opt_out_of_global_face_blur(env, monkeypatch):
    settings, conn = env
    monkeypatch.setattr(privacy_blur.FaceDetector, "detect", lambda self, bgr: pytest.fail("should not run"))
    render(settings, conn, _edl(settings, [{"src": f"{DAY1}/a.mp4", "in": 0, "out": 0.5, "blur_faces": False}],
                                audio="mute", blur_faces=True))


@pytest.mark.parametrize("box", [{"x": 0.9, "y": 0, "w": 0.2, "h": 0.1}, {"x": 0, "y": 0, "w": 0, "h": 0.1},
                                 {"x": 0, "y": 0, "w": "a", "h": 0.1}])
def test_bad_blur_box_rejected(settings, box):
    with pytest.raises(EDLError):
        _edl(settings, [{"src": "x.mp4", "in": 0, "out": 1, "blur": [box]}])


def test_privacy_scan_writes_report(env):
    from app.agents.media_librarian.privacy_scan import scan_video

    settings, conn = env
    video = render(settings, conn, _edl(settings, [{"src": f"{DAY1}/a.mp4", "in": 0, "out": 1.0}], audio="mute")).video
    out, n, faces = scan_video(settings, video)
    assert out.is_file() and n >= 2 and faces == 0
    assert "Check by eye" in out.read_text(encoding="utf-8")
