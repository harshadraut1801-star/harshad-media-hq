# db
**Purpose:** SQLite access layer. Tables: media, content, content_media, assets, approvals, posts, metrics, jobs, llm_calls, events (draft in `docs/ARCHITECTURE.md` §6.3).
**Rules:** schema changes only via `db/migrations/NNNN_*.sql`; WAL mode; database file is git-ignored.
**Status:** not implemented (next task #1).
