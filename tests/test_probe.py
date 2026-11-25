import pytest

from app.media.probe import kind_of, orientation_of, parse_iso6709, probe
from tests.media_factory import make_photo, make_video


def test_portrait_video_stored_landscape_with_rotation(tmp_path):
    info = probe(make_video(tmp_path / "a.mp4", w=320, h=180, rotation=-90))
    assert (info.width, info.height, info.orientation) == (180, 320, "portrait")
    assert info.rotation == -90
    assert info.vcodec == "h264" and info.acodec == "aac"
    assert info.duration_s == pytest.approx(2.0, abs=0.2)
    assert info.captured_at == "2026-11-25T07:18:37Z"


def test_landscape_video_and_gps(tmp_path):
    info = probe(make_video(tmp_path / "b.mp4", location="+19.8762+075.3433/"))
    assert info.orientation == "landscape"
    assert info.gps_lat == pytest.approx(19.8762) and info.gps_lon == pytest.approx(75.3433)


def test_photo_exif_orientation_and_ist_time(tmp_path):
    info = probe(make_photo(tmp_path / "p.jpg", w=400, h=185, orientation=6, gps=(19.88, 75.34)))
    assert (info.width, info.height, info.orientation) == (185, 400, "portrait")
    assert info.camera_model == "SM-G990E"
    assert info.captured_at == "2026-11-25T08:44:56Z"  # 14:14:56 IST
    assert info.gps_lat == pytest.approx(19.88, abs=0.001)


def test_helpers():
    assert kind_of(__import__("pathlib").Path("x.ZIP")) == "archive"
    assert orientation_of(1000, 1005) == "square"
    assert parse_iso6709("-33.8+151.2/") == (-33.8, 151.2)
    assert parse_iso6709(None) == (None, None)
