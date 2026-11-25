"""Load config/*.yaml plus .env into one Settings object.

PROJECT_ROOT is where the code and config live. MEDIA_ROOT is where the
numbered media folders live. They are the same folder by default; MEDIA_ROOT
can point elsewhere (e.g. a bigger drive) via .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

CONFIG_FILES = ("settings", "providers", "privacy", "render_presets")


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    project_root: Path
    media_root: Path
    settings: dict[str, Any]
    providers: dict[str, Any]
    privacy: dict[str, Any]
    render_presets: dict[str, Any]
    env: dict[str, str] = field(default_factory=dict, repr=False)  # never printed

    def media_path(self, key: str) -> Path:
        """Absolute path of a named media folder from settings.paths (e.g. 'raw_media')."""
        try:
            rel = self.settings["paths"][key]
        except KeyError as exc:
            raise ConfigError(f"settings.yaml has no paths.{key}") from exc
        return self.media_root / rel

    def project_path(self, key: str) -> Path:
        """Absolute path of a project-side folder/file from settings.paths (database, cache, logs)."""
        try:
            rel = self.settings["paths"][key]
        except KeyError as exc:
            raise ConfigError(f"settings.yaml has no paths.{key}") from exc
        return self.project_root / rel

    @property
    def raw_media(self) -> Path:
        return self.media_path("raw_media")

    @property
    def database(self) -> Path:
        return self.project_path("database")

    @property
    def monthly_budget_usd(self) -> float:
        return float(self.settings.get("budget", {}).get("monthly_budget_usd", 0) or 0)

    def secret(self, name: str) -> str | None:
        """Read a secret from the environment. Returns None if unset or empty."""
        value = self.env.get(name) or os.environ.get(name)
        return value or None


def _find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "config" / "settings.yaml").is_file():
            return candidate
    raise ConfigError(f"Could not find config/settings.yaml above {start}")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Missing config file: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def load_settings(project_root: Path | str | None = None) -> Settings:
    """Load settings. Root resolution order: argument, HQ_PROJECT_ROOT env, search upward from cwd."""
    if project_root is None:
        env_root = os.environ.get("HQ_PROJECT_ROOT")
        root = Path(env_root) if env_root else _find_project_root(Path.cwd())
    else:
        root = Path(project_root)
    root = root.resolve()

    env_file = root / ".env"
    env: dict[str, str] = {}
    if env_file.is_file():
        from dotenv import dotenv_values

        env = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
    load_dotenv(env_file, override=False)

    parts = {name: _read_yaml(root / "config" / f"{name}.yaml") for name in CONFIG_FILES}

    media_root_raw = env.get("MEDIA_ROOT") or os.environ.get("MEDIA_ROOT")
    media_root = Path(media_root_raw).resolve() if media_root_raw else root

    if "paths" not in parts["settings"] or "raw_media" not in parts["settings"]["paths"]:
        raise ConfigError("settings.yaml must define paths.raw_media")

    return Settings(project_root=root, media_root=media_root, env=env, **parts)
