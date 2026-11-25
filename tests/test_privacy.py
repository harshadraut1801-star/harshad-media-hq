from app.core.privacy import allows_external_ai, classify


def test_fnei_is_confidential(settings):
    p = settings.raw_media / "Jaipur Diaries" / "Customer Visit - FNEI" / "20261201_101500.mp4"
    assert classify(settings, p) == "confidential"


def test_trip_day_is_family_private(settings):
    p = settings.raw_media / "Jaipur Diaries" / "Day 03 - Jaipur" / "20261203_090000.mp4"
    assert classify(settings, p) == "family_private"


def test_marker_file_makes_folder_confidential(settings):
    folder = settings.raw_media / "Previous Trips" / "2025-01 Plant visit"
    folder.mkdir(parents=True)
    (folder / ".confidential").write_text("x")
    assert classify(settings, folder / "a.jpg") == "confidential"


def test_confidential_never_goes_to_external_ai(settings):
    assert allows_external_ai(settings, "confidential") is False
    assert allows_external_ai(settings, "family_private") is True
