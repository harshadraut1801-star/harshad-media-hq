from app.cli import main


def test_init_then_status(project, capsys):
    assert main(["--root", str(project), "init"]) == 0
    out = capsys.readouterr().out
    assert "0001_init.sql" in out
    assert (project / "02_SELECTED_FOOTAGE").is_dir()
    assert main(["--root", str(project), "status"]) == 0
    out = capsys.readouterr().out
    assert "schema v2" in out and "paid AI calls blocked" in out


def test_classify(project, capsys):
    main(["--root", str(project), "classify", "01_RAW_MEDIA/Jaipur Diaries/Customer Visit - FNEI/a.mp4"])
    assert capsys.readouterr().out.startswith("confidential")


def test_init_does_not_touch_raw_media(project):
    raw = project / "01_RAW_MEDIA"
    before = sorted(str(p.relative_to(raw)) for p in raw.rglob("*"))
    main(["--root", str(project), "init"])
    after = sorted(str(p.relative_to(raw)) for p in raw.rglob("*"))
    assert before == after
