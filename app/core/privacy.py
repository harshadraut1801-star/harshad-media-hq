"""Privacy classification of media paths from config/privacy.yaml.

Classes: public_ok | family_private | confidential. A file is confidential if it
sits under any configured confidential path, or under any folder containing the
marker file (default '.confidential'). Everything else gets the default class.
"""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .paths import is_inside

CLASSES = ("public_ok", "family_private", "confidential")


def classify(settings: Settings, path: Path | str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = settings.media_root / p
    cfg = settings.privacy

    for rel in cfg.get("confidential_paths", []) or []:
        if is_inside(p, settings.media_root / rel):
            return "confidential"

    marker = cfg.get("confidential_marker_file", ".confidential")
    for folder in (p if p.is_dir() else p.parent, *p.parents):
        if (folder / marker).exists():
            return "confidential"
        if folder == settings.media_root or folder == folder.parent:
            break

    default = cfg.get("default_class", "family_private")
    if default not in CLASSES:
        raise ValueError(f"privacy.yaml default_class must be one of {CLASSES}")
    return default


def allows_external_ai(settings: Settings, privacy_class: str) -> bool:
    rule = (settings.privacy.get("rules") or {}).get(privacy_class, {})
    return bool(rule.get("send_to_external_ai", False))
