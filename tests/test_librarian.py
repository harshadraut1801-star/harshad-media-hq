import json
import os
import stat

import pytest

from app.agents.media_librarian import scan, verify
from app.agents.media_librarian.report import summarise, write_html
from app.db import connect, migrate
from tests.media_factory import make_photo, make_video

DAY1 = "Jaipur Diaries/Day 01 - Aurangabad to Indore"
FNEI = "Jaipur Diaries/Customer Visit - FNEI"


@pytest.fixture()
def lib(settings):
    raw = settings.raw_media
    make_video(raw / DAY1 / "20261125_124826.mp4", rotation=-90)
    make_video(raw / DAY1 / "20261125_131724.mp4", seconds=1.0)
    make_photo(raw / DAY1 / "20261125_141456.jpg", gps=(19.88, 75.34))
    make_video(raw / FNEI / "20261126_101500.mp4")
    (raw / DAY1 / "drive-export.zip").write_bytes(b"PK")
    (raw / DAY1 / "dupe.mp4").write_bytes((raw / DAY1 / "20261125_124826.mp4").read_bytes())
    conn = connect(settings)
    migrate(settings, conn)
    return settings, conn


def _snapshot(folder):
    return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*") if p.is_file()}


def test_scan_catalogues_without_touching_originals(lib):
    settings, conn = lib
    before = _snapshot(settings.raw_media)
    res = scan(settings, conn)
    assert _snapshot(settings.raw_media) == before
    assert len(res.added) == 5
    assert res.skipped and "archive" in res.skipped[0][1]
    assert len(res.duplicates) == 1 and res.duplicates[0][0].endswith("dupe.mp4")


def test_scan_works_with_read_only_raw_folder(lib):
    settings, conn = lib
    if os.name == "nt" or os.geteuid() == 0:
        pytest.skip("permission bits not enforced for this user")
    for p in settings.raw_media.rglob("*"):
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    assert len(scan(settings, conn).added) == 5


def test_fields_privacy_and_location(lib):
    settings, conn = lib
    scan(settings, conn)
    rows = {r["rel_path"].rsplit("/", 1)[-1]: r for r in conn.execute("SELECT * FROM media")}
    v = rows["20261125_124826.mp4"]
    assert (v["orientation"], v["series"], v["day_folder"], v["privacy_class"]) == (
        "portrait", "JD", "Day 01 - Aurangabad to Indore", "family_private")
    assert rows["20261126_101500.mp4"]["privacy_class"] == "confidential"
    assert "very_short" in json.loads(rows["20261125_131724.mp4"]["notes"])
    assert "has_gps" in json.loads(rows["20261125_141456.jpg"]["notes"])
    assert v["thumb_path"] and (settings.project_root / v["thumb_path"]).is_file()


def test_rescan_is_incremental_and_detects_change_and_missing(lib):
    settings, conn = lib
    scan(settings, conn)
    res = scan(settings, conn)
    assert res.added == [] and res.unchanged == 5
    target = settings.raw_media / DAY1 / "20261125_131724.mp4"
    target.write_bytes(target.read_bytes() + b"x")   # simulate an outside edit (test only)
    (settings.raw_media / DAY1 / "dupe.mp4").unlink()
    res = scan(settings, conn)
    assert res.changed and res.changed[0].endswith("20261125_131724.mp4")
    assert res.missing and res.missing[0].endswith("dupe.mp4")
    out = verify(settings, conn)
    assert len(out["changed"]) == 1 and len(out["missing"]) == 1


def test_report_hides_confidential_thumbnail_and_gps(lib):
    settings, conn = lib
    scan(settings, conn)
    path = write_html(settings, summarise(conn))
    html = open(path, encoding="utf-8").read()
    assert "CONFIDENTIAL" in html
    assert "19.88" not in html and "75.34" not in html
    fnei_thumb = conn.execute("SELECT thumb_path FROM media WHERE privacy_class='confidential'").fetchone()[0]
    assert fnei_thumb.rsplit("/", 1)[-1] not in html
