# CLAUDE.md — Harshad Media HQ

Standing rules for any AI assistant (Claude or otherwise) working in this repository.
Read this file first, then `README.md`, then `docs/ARCHITECTURE.md`.

## What this is

An automated content production system for Harsh's travel media channels (Instagram + YouTube).
First series: **Jaipur Diaries** (Aurangabad → Indore → Jaipur family road trip, plus a professional customer visit).
Stack: Python 3.11+, FFmpeg/ffprobe, SQLite, n8n (self-hosted), Claude via a configurable provider layer.

## Hard rules (non-negotiable)

1. **Originals are read-only.** Nothing under `01_RAW_MEDIA/` is ever modified, renamed, moved, re-encoded in place or deleted. Code reads originals and writes derived files elsewhere. The path guard in `app/core` must reject any write whose target resolves inside `01_RAW_MEDIA/`.
2. **No publishing without approval.** Nothing goes to Instagram, YouTube or any public surface unless a human approval record exists in the database for that exact rendered file (matched by SHA-256). The publisher refuses otherwise. No "auto-publish" flag exists, and none should be added.
3. **No spending without approval.** Do not sign up for, upgrade or purchase any subscription, plan, API tier, stock asset or paid voice/music service. Pay-per-use API calls (Claude, TTS) run only within the budget cap set in `config/settings.yaml`; raising the cap is Harsh's decision.
4. **Privacy and confidentiality by default.**
   - `01_RAW_MEDIA/Jaipur Diaries/Customer Visit - FNEI/` is **confidential**. Its media is never selected for public content automatically, never sent to an external AI provider, and never named publicly. Only Harsh can reclassify a specific file, in writing, and that decision is logged.
   - Family media is `family_private` until approved for a specific piece of content. Children's faces, home locations, vehicle number plates, hotel room numbers and live location are treated as sensitive.
   - Strip GPS and device metadata from every exported file (`-map_metadata -1` and equivalent for images).
   - Default to posting about a place after the family has left it, not live.
5. **Secrets never enter the repo.** API keys and tokens live only in `.env` (git-ignored). Only `.env.example` with empty placeholders is committed. Never print, log or paste a key into a doc, prompt, commit, issue or chat.
6. **Build incrementally.** One component at a time, each with a working CLI entry point, tests and a doc update before moving on. Do not scaffold all agents at once.
7. **Document every component.** Each folder under `app/` has a `README.md` stating purpose, inputs, outputs, status and open questions. Update it in the same change that alters behaviour. Record notable decisions in `docs/decisions/` (one short ADR per decision).
8. **Truthfulness.** Captions, scripts and descriptions must not invent facts about places, the family, the business or its customers. R. P. Industries is ISO 9000 in progress and does not hold AS9100; never claim otherwise.

## Working conventions

- Configuration in YAML under `config/`, secrets in `.env`, both loaded by `app/core/config`.
- Paths: always resolve from `MEDIA_ROOT` / `PROJECT_ROOT` settings, never hard-code `D:\...`.
- Database: single SQLite file `db/hq.sqlite3`, schema changes only via numbered SQL files in `db/migrations/`.
- LLM calls: only through `app/providers`. No agent imports an SDK directly. Model names come from `config/providers.yaml`.
- FFmpeg/ffprobe: only through `app/media` wrappers, which log the exact command line for reproducibility.
- Every derived file records its lineage (source media IDs + recipe) in the database.
- Long renders and batch jobs are queued through the orchestrator, not run inline in the dashboard.
- Tests in `tests/`, runnable with `pytest`. Tests use small synthetic clips, never real family media.

## Things to ask Harsh before doing

- Anything that costs money, publishes, contacts a customer, or sends media/transcripts to a new external service.
- Changing a privacy classification.
- Deleting anything outside `cache/` and `logs/`.

## Status

Foundation + task 1 (core plumbing) done. No agent is implemented yet. Write files only via `app.core.paths.safe_write_path()` / `open_for_write()`. See `docs/ARCHITECTURE.md` §10 for the build order.
