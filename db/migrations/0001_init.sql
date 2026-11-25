-- 0001_init: initial schema. See docs/ARCHITECTURE.md §6.3.

CREATE TABLE media (
    id              INTEGER PRIMARY KEY,
    rel_path        TEXT NOT NULL UNIQUE,          -- relative to MEDIA_ROOT, forward slashes
    sha256          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('video','photo','audio','other')),
    duration_s      REAL,
    width           INTEGER,
    height          INTEGER,
    rotation        INTEGER,                       -- display rotation in degrees
    orientation     TEXT CHECK (orientation IN ('portrait','landscape','square')),
    fps             REAL,
    vcodec          TEXT,
    acodec          TEXT,
    hdr             INTEGER NOT NULL DEFAULT 0,
    captured_at     TEXT,                          -- ISO 8601, from metadata
    gps_lat         REAL,                          -- internal only, never exported
    gps_lon         REAL,
    series          TEXT,
    trip_folder     TEXT,
    day_folder      TEXT,
    privacy_class   TEXT NOT NULL DEFAULT 'family_private'
                    CHECK (privacy_class IN ('public_ok','family_private','confidential')),
    tags            TEXT,                          -- JSON array
    status          TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','missing','changed')),
    ingested_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    verified_at     TEXT
);
CREATE INDEX idx_media_sha ON media(sha256);
CREATE INDEX idx_media_privacy ON media(privacy_class);

CREATE TABLE content (
    id              TEXT PRIMARY KEY,              -- JD-R-003
    series          TEXT NOT NULL,
    format          TEXT NOT NULL CHECK (format IN ('reel','short','long')),
    title           TEXT,
    state           TEXT NOT NULL DEFAULT 'idea',
    platform_targets TEXT,                         -- JSON array
    planned_date    TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE content_media (
    content_id      TEXT NOT NULL REFERENCES content(id),
    media_id        INTEGER NOT NULL REFERENCES media(id),
    position        INTEGER NOT NULL,
    in_s            REAL,
    out_s           REAL,
    role            TEXT CHECK (role IN ('a-roll','b-roll','still')),
    PRIMARY KEY (content_id, position)
);

CREATE TABLE assets (
    id              INTEGER PRIMARY KEY,
    content_id      TEXT NOT NULL REFERENCES content(id),
    kind            TEXT NOT NULL CHECK (kind IN ('script','srt','caption','voice','music','mix','video','thumbnail','manifest')),
    path            TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    recipe_json     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE approvals (
    id              INTEGER PRIMARY KEY,
    content_id      TEXT NOT NULL REFERENCES content(id),
    asset_hashes    TEXT NOT NULL,                 -- JSON {kind: sha256}
    decision        TEXT NOT NULL CHECK (decision IN ('approved','rejected')),
    note            TEXT,
    decided_by      TEXT NOT NULL,
    decided_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE posts (
    id              INTEGER PRIMARY KEY,
    content_id      TEXT NOT NULL REFERENCES content(id),
    platform        TEXT NOT NULL CHECK (platform IN ('instagram','youtube')),
    platform_post_id TEXT,
    url             TEXT,
    published_at    TEXT
);

CREATE TABLE metrics (
    post_id         INTEGER NOT NULL REFERENCES posts(id),
    captured_at     TEXT NOT NULL,
    views INTEGER, reach INTEGER, likes INTEGER, comments INTEGER,
    shares INTEGER, saves INTEGER, watch_time_s REAL, avg_view_pct REAL,
    PRIMARY KEY (post_id, captured_at)
);

CREATE TABLE jobs (
    id              INTEGER PRIMARY KEY,
    type            TEXT NOT NULL,
    payload_json    TEXT,
    status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed','cancelled')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT,
    finished_at     TEXT,
    log_path        TEXT
);

CREATE TABLE llm_calls (
    id              INTEGER PRIMARY KEY,
    role            TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    est_cost_usd    REAL NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE events (
    id              INTEGER PRIMARY KEY,
    entity          TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    from_state      TEXT,
    to_state        TEXT,
    actor           TEXT NOT NULL,
    note            TEXT,
    at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
