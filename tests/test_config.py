import pytest

from app.core.config import ConfigError, load_settings


def test_defaults(settings, project):
    assert settings.project_root == project.resolve()
    assert settings.media_root == project.resolve()
    assert settings.raw_media == project.resolve() / "01_RAW_MEDIA"
    assert settings.monthly_budget_usd == 0


def test_media_root_from_env_file(project, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (project / ".env").write_text(f"MEDIA_ROOT={media}\nANTHROPIC_API_KEY=\n", encoding="utf-8")
    s = load_settings(project)
    assert s.media_root == media.resolve()
    assert s.secret("ANTHROPIC_API_KEY") is None  # empty means unset


def test_missing_config_raises(project):
    (project / "config" / "privacy.yaml").unlink()
    with pytest.raises(ConfigError):
        load_settings(project)


def test_settings_repr_hides_env(project):
    (project / ".env").write_text("ANTHROPIC_API_KEY=sk-secret-value\n", encoding="utf-8")
    s = load_settings(project)
    assert "sk-secret-value" not in repr(s)
