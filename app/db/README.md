# db
**Purpose:** SQLite access layer. Tables: media, content, content_media, assets, approvals, posts, metrics, jobs, llm_calls, events (draft in `docs/ARCHITECTURE.md` §6.3).
**Rules:** schema changes only via `db/migrations/NNNN_*.sql`; WAL mode; database file is git-ignored.
**Status:** v0.1 implemented. `connect()` (WAL, foreign keys, path-guarded), `migrate()` applies `db/migrations/NNNN_*.sql` once each in a transaction, `schema_version()`. Schema v1 = `0001_init.sql`.
