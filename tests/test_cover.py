import pytest
from PIL import Image

from app.agents.video_editor import load_edl, render
from app.agents.video_editor.cover import (CoverError, caption_windows, candidates, compose, grid_preview,
                                           make_cover)
from app.cli import main
from app.db import connect, migrate
from app.orchestrator.approval import find_package
from tests.media_factory import make_photo, make_video

DAY1 = "01_RAW_MEDIA/Jaipur Diaries/Day 01 - Aurangabad to Indore"


@pytest.fixture()
def rendered(settings):
    import yaml

    settings.render_presets["reel"].update(width=216, height=384)
    settings.render_presets["segment_fade_s"] = 0
    make_video(settings.media_root / DAY1 / "a.mp4", w=384, h=216, seconds=2, rotation=-90)
    make_photo(settings.media_root / DAY1 / "p.jpg", w=800, h=400)
    folder = settings.media_root / "02_SELECTED_FOOTAGE" / "Jaipur Diaries" / "JD-R-009"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "edl.yaml").write_text(yaml.safe_dump({
        "content_id": "JD-R-009", "series": "Jaipur Diaries", "format": "reel", "title": "Test",
        "segments": [{"src": f"{DAY1}/a.mp4", "in": 0, "out": 1.5, "caption": "hello"},
                     {"src": f"{DAY1}/p.jpg", "duration": 1.5}]}), encoding="utf-8")
    conn = connect(settings)
    migrate(settings, conn)
    res = render(settings, conn, load_edl(folder / "edl.yaml"))
    return settings, conn, res.video


def test_caption_windows_from_manifest():
    m = {"segments": [{"duration": 2, "caption": "a"}, {"duration": 1.5}, {"duration": 1, "caption": "b"}]}
    assert caption_windows(m) == [(0.0, 2.0), (3.5, 4.5)]


def test_candidates_written_without_metadata(rendered):
    settings, conn, video = rendered
    report, cands = candidates(settings, video, "Jaipur Diaries", "JD-R-009", n=4, conn=conn)
    assert report.is_file() and 1 <= len(cands) <= 4
    assert cands == sorted(cands, key=lambda c: c.score, reverse=True)
    for c in cands:
        f = report.parent / c.file
        assert f.is_file()
        assert c.caption_on_screen == (c.t < 1.5)
        with Image.open(f) as im:
            assert not im.getexif()
    assert "hq cover JD-R-009 --t" in report.read_text(encoding="utf-8")


def test_make_cover_feeds_approval_package(rendered):
    settings, conn, video = rendered
    res = make_cover(settings, video, "Jaipur Diaries", "JD-R-009", t=2.0, title="Day 01: test road",
                     subtitle="Jaipur Diaries", conn=conn)
    with Image.open(res.thumbnail) as im:
        assert im.size == (1080, 1920)
        assert not im.getexif()
    with Image.open(res.grid_preview) as im:
        assert im.size == (1080, 1440)
    pkg = find_package(settings, "JD-R-009", "Jaipur Diaries")
    assert pkg.thumbnail == res.thumbnail
    row = conn.execute("SELECT sha256, version FROM assets WHERE kind='thumbnail' AND content_id='JD-R-009'").fetchone()
    assert row["sha256"] == res.sha256 and row["version"] == 1
    res2 = make_cover(settings, video, "Jaipur Diaries", "JD-R-009", t=0.5, title="Another", conn=conn)
    assert res2.version == 2 and res.cover.is_file()          # older cover kept


def test_cover_needs_title_and_valid_time(rendered):
    settings, conn, video = rendered
    with pytest.raises(CoverError, match="title"):
        make_cover(settings, video, "Jaipur Diaries", "JD-R-009", t=1.0, title="  ")
    with pytest.raises(CoverError, match="past the end"):
        make_cover(settings, video, "Jaipur Diaries", "JD-R-009", t=99, title="x")


def test_cover_refuses_confidential_content(rendered):
    settings, conn, video = rendered
    conn.execute("INSERT INTO media (id, rel_path, sha256, size_bytes, kind, privacy_class) "
                 "VALUES (99,'x/fnei.mp4','h',1,'video','confidential')")
    conn.execute("INSERT INTO content_media (content_id, media_id, position) VALUES ('JD-R-009', 99, 9)")
    conn.commit()
    with pytest.raises(CoverError, match="confidential"):
        make_cover(settings, video, "Jaipur Diaries", "JD-R-009", t=1.0, title="x", conn=conn)


def test_long_format_and_grid_crop(settings):
    frame = Image.new("RGB", (1920, 1080), (40, 90, 160))
    img = compose(settings, frame, "A fairly long title that has to wrap over lines", None, "long")
    assert img.size == (1280, 720)
    assert grid_preview(img).size == (1280, 720)


def test_cli_covers_and_cover(rendered, capsys):
    settings, conn, video = rendered
    root = str(settings.project_root)
    assert main(["--root", root, "covers", "JD-R-009", "--n", "3"]) == 0
    assert main(["--root", root, "cover", "JD-R-009", "--t", "1.8", "--title", "Road day"]) == 0
    out = capsys.readouterr().out
    assert "candidates" in out and "Cover v1" in out
