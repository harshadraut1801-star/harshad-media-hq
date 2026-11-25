"""Fixtures: a throwaway copy of the project skeleton (config + migrations + folders)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.config import load_settings

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def project(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "Harshad Media HQ"
    root.mkdir()
    shutil.copytree(REPO / "config", root / "config")
    shutil.copytree(REPO / "db" / "migrations", root / "db" / "migrations")
    shutil.copytree(REPO / "01_RAW_MEDIA", root / "01_RAW_MEDIA")
    shutil.copy(REPO / ".gitignore", root / ".gitignore")
    monkeypatch.delenv("MEDIA_ROOT", raising=False)
    monkeypatch.delenv("HQ_PROJECT_ROOT", raising=False)
    return root


@pytest.fixture()
def settings(project):
    return load_settings(project)
