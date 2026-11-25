import os

import pytest

from app.core.paths import RawMediaWriteError, open_for_write, safe_write_path


def test_write_outside_raw_is_allowed(settings):
    p = safe_write_path(settings, "05_EDITED_VIDEOS/Jaipur Diaries/JD-R-001/draft.txt")
    assert p.parent.is_dir()


@pytest.mark.parametrize(
    "target",
    [
        "01_RAW_MEDIA/new.mp4",
        "01_RAW_MEDIA/Jaipur Diaries/Day 02 - Indore/clip.mp4",
        "05_EDITED_VIDEOS/../01_RAW_MEDIA/sneaky.mp4",
        "01_RAW_MEDIA",
    ],
)
def test_write_into_raw_is_refused(settings, target):
    with pytest.raises(RawMediaWriteError):
        safe_write_path(settings, target)


def test_absolute_path_into_raw_is_refused(settings):
    with pytest.raises(RawMediaWriteError):
        safe_write_path(settings, settings.raw_media / "Previous Trips" / "x.jpg")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlink support")
def test_symlink_into_raw_is_refused(settings, project):
    link = project / "05_EDITED_VIDEOS"
    link.parent.mkdir(exist_ok=True)
    try:
        os.symlink(settings.raw_media, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    with pytest.raises(RawMediaWriteError):
        safe_write_path(settings, link / "evil.mp4")


def test_open_for_write_refuses_raw(settings):
    with pytest.raises(RawMediaWriteError):
        open_for_write(settings, "01_RAW_MEDIA/notes.txt")


def test_open_for_write_rejects_read_mode(settings):
    with pytest.raises(ValueError):
        open_for_write(settings, "cache/x.txt", "r")


def test_raw_folder_with_similar_name_is_not_confused(settings):
    # '01_RAW_MEDIA_backup' must not be treated as inside '01_RAW_MEDIA'
    p = safe_write_path(settings, "01_RAW_MEDIA_backup/x.txt")
    assert p.name == "x.txt"
