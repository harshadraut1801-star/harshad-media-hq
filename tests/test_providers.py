import pytest

from app.core.config import ConfigError
from app.db import connect, migrate
from app.providers import BudgetExceededError, ConfidentialMediaError, get_provider
from app.providers.base import DryRunProvider, LLMProvider, LLMResult


@pytest.fixture()
def conn(settings):
    c = connect(settings)
    migrate(settings, c)
    c.execute("INSERT INTO media (id, rel_path, sha256, size_bytes, kind, privacy_class) VALUES (1,'a.mp4','x',1,'video','family_private')")
    c.execute("INSERT INTO media (id, rel_path, sha256, size_bytes, kind, privacy_class) VALUES (2,'fnei.mp4','y',1,'video','confidential')")
    c.commit()
    return c


def test_dryrun_works_and_logs(settings, conn):
    p = DryRunProvider(settings, conn, "none")
    r = p.complete("writer", [{"role": "user", "content": "hello"}], media_ids=[1])
    assert r.text.startswith("[dry-run]")
    assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 1


def test_confidential_media_blocked(settings, conn):
    p = DryRunProvider(settings, conn, "none")
    with pytest.raises(ConfidentialMediaError):
        p.complete("writer", [{"role": "user", "content": "x"}], media_ids=[1, 2])
    assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0


def test_unknown_media_blocked(settings, conn):
    p = DryRunProvider(settings, conn, "none")
    with pytest.raises(ConfidentialMediaError):
        p.complete("writer", [{"role": "user", "content": "x"}], media_ids=[99])


class FakePaid(LLMProvider):
    name = "fakepaid"

    def _complete(self, messages):
        return LLMResult(text="ok", provider=self.name, model=self.model, est_cost_usd=0.5)


def test_paid_blocked_at_zero_budget(settings, conn):
    with pytest.raises(BudgetExceededError):
        FakePaid(settings, conn, "m").complete("writer", [{"role": "user", "content": "x"}], est_cost_usd=0.01)


def test_paid_blocked_over_cap(settings, conn):
    settings.settings["budget"]["monthly_budget_usd"] = 1.0
    p = FakePaid(settings, conn, "m")
    p.complete("writer", [{"role": "user", "content": "x"}], est_cost_usd=0.5)
    p.complete("writer", [{"role": "user", "content": "x"}], est_cost_usd=0.5)
    with pytest.raises(BudgetExceededError):
        p.complete("writer", [{"role": "user", "content": "x"}], est_cost_usd=0.5)


def test_unimplemented_provider_gives_clear_error(settings, conn):
    with pytest.raises(ConfigError, match="not implemented yet"):
        get_provider(settings, conn, "writer")
