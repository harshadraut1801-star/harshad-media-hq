"""Path helpers and the raw-media write guard.

Rule: nothing under 01_RAW_MEDIA is ever written, renamed, moved or deleted by
code. Every writer must obtain its target through safe_write_path() (or
open_for_write()), which refuses any path that resolves inside the raw folder,
including via '..', symlinks or case differences on Windows.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from .config import Settings


class RawMediaWriteError(PermissionError):
    """Raised when code attempts to write inside 01_RAW_MEDIA."""


def _norm(path: Path) -> str:
    # resolve() follows symlinks; normcase lowers case and fixes slashes on Windows.
    return os.path.normcase(str(path.resolve()))


def is_inside(path: Path, folder: Path) -> bool:
    p, f = _norm(path), _norm(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def is_raw_media(settings: Settings, path: Path | str) -> bool:
    return is_inside(Path(path), settings.raw_media)


def safe_write_path(settings: Settings, path: Path | str, *, mkdir: bool = True) -> Path:
    """Return the resolved path if it is safe to write, else raise RawMediaWriteError."""
    target = Path(path)
    if not target.is_absolute():
        target = settings.project_root / target
    if is_raw_media(settings, target):
        raise RawMediaWriteError(
            f"Refusing to write inside raw media (read-only): {target}"
        )
    resolved = target.resolve()
    if mkdir:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def open_for_write(settings: Settings, path: Path | str, mode: str = "w", **kwargs) -> IO:
    """open() wrapper that enforces the guard. Use for every file the app writes."""
    if not any(ch in mode for ch in "wax+"):
        raise ValueError("open_for_write is for write modes; use open() to read")
    if "b" not in mode:
        kwargs.setdefault("encoding", "utf-8")
    return open(safe_write_path(settings, path), mode, **kwargs)


def rel_to_media_root(settings: Settings, path: Path | str) -> str:
    """Media-root-relative path with forward slashes, as stored in the database."""
    return Path(path).resolve().relative_to(settings.media_root).as_posix()
