# orchestrator
**Purpose:** SQLite-backed job queue + content state machine (idea → … → pending_approval → approved → published → measured). Sequences agents; agents never call each other. Only Harsh can move `pending_approval → approved`. Publish jobs are never auto-retried.
**Interface:** `hq` CLI (`hq run`, `hq status`) used by n8n and the dashboard.
**Status:** not implemented.
