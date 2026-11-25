# ADR 0001 — Local-first: Python core, SQLite, n8n as glue

**Date:** 2026-11-25 · **Status:** accepted (foundation)

**Context:** One operator, Windows PC, media is large and private, no budget for subscriptions yet.
**Decision:** Python owns media processing, state and rules; SQLite is the single source of truth; n8n (self-hosted) only schedules and glues; Claude via a provider layer.
**Consequences:** Zero fixed cost, works offline except AI/publish calls, easy backup (one folder + one DB file). Concurrency is limited (single worker), acceptable at this scale. Revisit if multiple editors or a server deployment are needed.
