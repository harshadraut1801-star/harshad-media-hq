"""LLM provider interface plus the two guards every call passes through.

1. Confidential guard: a request that references any media ID classed
   'confidential' (or any class that forbids external AI) fails before anything
   leaves the machine.
2. Budget guard: spend this calendar month (from llm_calls) plus the call's
   estimate must stay within settings.budget.monthly_budget_usd. Budget 0 means
   paid calls are blocked. The dry-run provider is free and always allowed.

Real vendors (Anthropic first) are added with the Travel Storyteller task.
"""
from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from app.core.config import ConfigError, Settings
from app.core.privacy import allows_external_ai


class ConfidentialMediaError(PermissionError):
    pass


class BudgetExceededError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost_usd: float = 0.0


class LLMProvider(ABC):
    name: str = "base"
    is_paid: bool = True

    def __init__(self, settings: Settings, conn: sqlite3.Connection, model: str):
        self.settings = settings
        self.conn = conn
        self.model = model

    # --- public entry point ------------------------------------------------
    def complete(
        self,
        role: str,
        messages: list[dict],
        *,
        media_ids: Iterable[int] = (),
        est_cost_usd: float = 0.0,
    ) -> LLMResult:
        self._check_media(media_ids)
        if self.is_paid:
            self._check_budget(est_cost_usd)
        result = self._complete(messages)
        self.conn.execute(
            "INSERT INTO llm_calls (role, provider, model, tokens_in, tokens_out, est_cost_usd)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (role, result.provider, result.model, result.tokens_in, result.tokens_out, result.est_cost_usd),
        )
        self.conn.commit()
        return result

    @abstractmethod
    def _complete(self, messages: list[dict]) -> LLMResult: ...

    # --- guards -------------------------------------------------------------
    def _check_media(self, media_ids: Iterable[int]) -> None:
        ids = list(media_ids)
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT id, privacy_class FROM media WHERE id IN ({marks})", ids
        ).fetchall()
        known = {r["id"]: r["privacy_class"] for r in rows}
        unknown = set(ids) - set(known)
        if unknown:
            raise ConfidentialMediaError(f"Unknown media IDs (refusing to send): {sorted(unknown)}")
        blocked = [i for i, cls in known.items() if not allows_external_ai(self.settings, cls)]
        if blocked:
            raise ConfidentialMediaError(f"Media not allowed to leave this machine: {sorted(blocked)}")

    def _check_budget(self, est_cost_usd: float) -> None:
        cap = self.settings.monthly_budget_usd
        spent = self.conn.execute(
            "SELECT COALESCE(SUM(est_cost_usd), 0) FROM llm_calls"
            " WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
        ).fetchone()[0]
        if cap <= 0:
            raise BudgetExceededError("AI budget cap is 0 (set budget.monthly_budget_usd in config/settings.yaml)")
        if spent + est_cost_usd > cap:
            raise BudgetExceededError(f"Monthly AI budget would be exceeded: spent ${spent:.2f} of ${cap:.2f}")


class DryRunProvider(LLMProvider):
    """Free, offline provider for wiring and tests. Echoes a placeholder."""

    name = "dryrun"
    is_paid = False

    def _complete(self, messages: list[dict]) -> LLMResult:
        last = messages[-1]["content"] if messages else ""
        return LLMResult(text=f"[dry-run] {last[:200]}", provider=self.name, model=self.model)


_REGISTRY: dict[str, type[LLMProvider]] = {"dryrun": DryRunProvider}


def get_provider(settings: Settings, conn: sqlite3.Connection, role: str) -> LLMProvider:
    roles = settings.providers.get("roles", {})
    if role not in roles:
        raise ConfigError(f"providers.yaml has no role '{role}'")
    spec = roles[role]
    provider_name = spec.get("provider", settings.providers.get("default_provider"))
    cls = _REGISTRY.get(provider_name)
    if cls is None:
        raise ConfigError(
            f"Provider '{provider_name}' for role '{role}' is not implemented yet. "
            "Use provider: dryrun until the Storyteller task adds it."
        )
    return cls(settings, conn, spec.get("model", "none"))
