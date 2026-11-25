import json
import shutil

import pytest

from app.cli import main
from app.db import connect, migrate
from app.orchestrator.approval import ApprovalError, approve, check, reject, submit
from app.orchestrator.state import TransitionError, transition

SERIES = "Jaipur Diaries"
HUMAN = "human:harsh"


@pytest.fixture()
def env(settings):
    folder = settings.media_path("edited") / SERIES / "JD-R-001"
    folder.mkdir(parents=True)
    (folder / "JD-R-001_v1.mp4").write_bytes(b"video-one")
    (folder / "JD-R-001_v2.mp4").write_bytes(b"video-two")
    cap = settings.media_path("scripts") / SERIES / "JD-R-001"
    cap.mkdir(parents=True)
    (cap / "caption.txt").write_text("Day 01 on the road.", encoding="utf-8")
    conn = connect(settings)
    migrate(settings, conn)
    return settings, conn


def test_full_approval_creates_ready_package(env):
    settings, conn = env
    pkg = submit(settings, conn, "JD-R-001", SERIES, actor=HUMAN)
    assert pkg.video.name == "JD-R-001_v2.mp4"               # latest version
    ready = approve(settings, conn, "JD-R-001", SERIES, actor=HUMAN, checklist_confirmed=True)
    manifest = json.loads((ready / "manifest.json").read_text())
    assert manifest["files"] == {"video": "JD-R-001_v2.mp4", "caption": "caption.txt"}
    assert (ready / "JD-R-001_v2.mp4").read_bytes() == b"video-two"
    assert conn.execute("SELECT state FROM content WHERE id='JD-R-001'").fetchone()[0] == "approved"
    assert check(settings, conn, "JD-R-001") == (True, "approval #1 valid")


def test_agents_cannot_approve(env):
    settings, conn = env
    submit(settings, conn, "JD-R-001", SERIES, actor=HUMAN)
    for actor in ("video_editor", "publisher", "system", "harsh"):
        with pytest.raises((ApprovalError, TransitionError)):
            approve(settings, conn, "JD-R-001", SERIES, actor=actor, checklist_confirmed=True)
    with pytest.raises(TransitionError):
        transition(conn, "JD-R-001", "approved", actor="executive_producer")


def test_checklist_required(env):
    settings, conn = env
    submit(settings, conn, "JD-R-001", SERIES, actor=HUMAN)
    with pytest.raises(ApprovalError, match="checklist"):
        approve(settings, conn, "JD-R-001", SERIES, actor=HUMAN, checklist_confirmed=False)


def test_must_submit_before_approve(env):
    settings, conn = env
    with pytest.raises(ApprovalError, match="submit"):
        approve(settings, conn, "JD-R-001", SERIES, actor=HUMAN, checklist_confirmed=True)


@pytest.mark.parametrize("tamper", ["video", "caption", "delete"])
def test_any_change_voids_approval(env, tamper):
    settings, conn = env
    submit(settings, conn, "JD-R-001", SERIES, actor=HUMAN)
    ready = approve(settings, conn, "JD-R-001", SERIES, actor=HUMAN, checklist_confirmed=True)
    if tamper == "video":
        (ready / "JD-R-001_v2.mp4").write_bytes(b"edited later")
    elif tamper == "caption":
        (ready / "caption.txt").write_text("changed caption", encoding="utf-8")
    else:
        (ready / "caption.txt").unlink()
    ok, msg = check(settings, conn, "JD-R-001")
    assert not ok and "void" in msg
    assert conn.execute("SELECT state FROM content WHERE id='JD-R-001'").fetchone()[0] == "pending_approval"


def test_reject_needs_note_and_logs(env):
    settings, conn = env
    submit(settings, conn, "JD-R-001", SERIES, actor=HUMAN)
    with pytest.raises(ApprovalError):
        reject(settings, conn, "JD-R-001", actor=HUMAN, note="  ")
    reject(settings, conn, "JD-R-001", actor=HUMAN, note="drop the couple photo")
    assert conn.execute("SELECT state FROM content WHERE id='JD-R-001'").fetchone()[0] == "rejected"
    notes = [r[0] for r in conn.execute("SELECT note FROM events WHERE entity_id='JD-R-001'")]
    assert "drop the couple photo" in notes
    assert not check(settings, conn, "JD-R-001")[0]


def test_confidential_media_blocks_approval(env):
    settings, conn = env
    submit(settings, conn, "JD-R-001", SERIES, actor=HUMAN)
    conn.execute("INSERT INTO media (id, rel_path, sha256, size_bytes, kind, privacy_class) "
                 "VALUES (9,'x/fnei.mp4','h',1,'video','confidential')")
    conn.execute("INSERT INTO content_media (content_id, media_id, position) VALUES ('JD-R-001', 9, 1)")
    conn.commit()
    with pytest.raises(ApprovalError, match="confidential"):
        approve(settings, conn, "JD-R-001", SERIES, actor=HUMAN, checklist_confirmed=True)


def test_cli_flow(env, project, capsys, monkeypatch):
    r = ["--root", str(project)]
    assert main(r + ["submit", "JD-R-001"]) == 0
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(r + ["approve", "JD-R-001"]) == 1                  # no silent approval
    assert main(r + ["approve", "JD-R-001", "--checklist-ok"]) == 0
    assert main(r + ["check", "JD-R-001"]) == 0
    main(r + ["review"])
    assert "approved" in capsys.readouterr().out
