# Harshad Media HQ — Architecture (v0.1, foundation)

Date: 25 Nov 2026 · Status: draft for review · Owner: Harsh

## 1. Purpose and scope

Turn raw phone and archive footage into publish-ready Instagram Reels, YouTube Shorts and long-form YouTube videos, with AI doing the grunt work (cataloguing, scripting, rough cuts, subtitles, captions, thumbnails, metrics) and Harsh approving everything that goes public.

Out of scope for v0.x: multi-user access, cloud hosting, paid stock libraries, fully automatic publishing.

## 2. Design principles

| Principle | What it means in practice |
|---|---|
| Originals are sacred | `01_RAW_MEDIA` is read-only to code. Everything else is derived and rebuildable. |
| Database is the brain, folders are the shelves | SQLite holds state, lineage and approvals. Folders hold files a human can browse in Explorer. |
| Deterministic core, AI at the edges | FFmpeg, hashing, state transitions are plain code. LLMs propose scripts, selections and captions; code validates them. |
| Human gate before public | Approval is a database record tied to a file hash, not a folder move. |
| Provider-agnostic | Agents ask for "a writing model" or "a vision model"; config maps that to Claude (default) or another provider. |
| Incremental | Every component ships with a CLI, tests and docs before the next one starts. |
| Local first, zero fixed cost | Runs on Harsh's Windows PC. Only pay-per-use API calls, capped by budget. |

## 3. System context

```
 Samsung S21 FE ──copy──► 01_RAW_MEDIA (read-only)
 Archive drives ──copy──┘        │
                                 ▼
                    ┌──────── Python app (app/) ─────────┐
   Telegram ◄──────►│ orchestrator ─► agents ─► media    │──► 02…07 stage folders
   (notify/approve) │      │            │      (FFmpeg)  │
                    │      ▼            ▼                │
   n8n ────trigger─►│   SQLite db   providers ──────────►│──► Claude API (and others, optional)
   (schedules,      │                                    │
    glue)           └──────── dashboard (localhost) ─────┘
                                 │ approve
                                 ▼
                    publisher ──► Instagram Graph API / YouTube Data API ──► 08_PUBLISHED_CONTENT
                                 ▲
                    growth analyst ◄── metrics APIs
```

**Split of responsibility between Python and n8n.** Python owns media processing, state and rules. n8n owns schedules and glue: "every night, run the librarian scan", "every morning, pull yesterday's metrics", "send the Telegram approval prompt". n8n calls the Python CLI (Execute Command) or a small local HTTP endpoint. Business rules never live only in n8n, so the system still works if n8n is off.

## 4. Media library and production line

### 4.1 Folders

| Folder | Holds | Written by | Notes |
|---|---|---|---|
| `01_RAW_MEDIA/` | Originals, as copied off the phone | Harsh only | Read-only to code. Filenames untouched. |
| `02_SELECTED_FOOTAGE/` | Clips chosen for a content piece: trimmed segments, stabilised or reframed versions | Video Editor | Rebuildable from 01 + recipe |
| `03_AI_SCRIPTS/` | Outlines, scripts, captions, hashtags, `.srt` subtitles, title options | Storyteller | Text, versioned |
| `04_VOICEOVERS/` | Narration takes, TTS output, music beds, final mix | Audio Producer | WAV masters, AAC for render |
| `05_EDITED_VIDEOS/` | Rendered drafts (`reel`, `short`, `long`) with version suffix | Video Editor | `JD-R-003_v2.mp4` |
| `06_THUMBNAILS/` | Thumbnail and cover candidates, chosen final | Storyteller + Editor | 1280×720 YT, 1080×1920 cover |
| `07_READY_TO_PUBLISH/` | Approved package per piece: video, caption, thumbnail, `manifest.json` | Executive Producer after approval | Only approved items land here |
| `08_PUBLISHED_CONTENT/` | What went live + platform IDs, URLs, publish time | Publisher | Archive, never edited |

Filing inside stages 02–08: `<Series>/<content_id>/`. Content IDs: `JD-R-###` (Jaipur Diaries Reel), `JD-S-###` (Short), `JD-L-###` (long-form).

### 4.2 Read-only enforcement

- `app/core/paths.py` will provide `safe_write_path()`; every writer goes through it, and it raises if the resolved target is inside `01_RAW_MEDIA`.
- The librarian opens originals read-only and never calls rename/move/delete on them.
- Optional extra layer on Windows: mark `01_RAW_MEDIA` read-only for the account the app runs under.
- Integrity: each original's SHA-256 is stored at ingest. A periodic check flags any change or disappearance (it reports; it never "fixes").

### 4.3 Samsung S21 FE specifics to handle

- Videos are often stored landscape with a **rotation flag** for portrait. Orientation must come from ffprobe display matrix / side data, not from width × height alone.
- Codec may be H.264 or **HEVC (H.265)** depending on camera settings; HDR10+ clips need tone-mapping before SDR export.
- Variable frame rate is common on phone footage; renders normalise to constant 30 fps (or 25/60 per preset).
- Photos may be JPEG or HEIC; **Motion Photos** embed a short video in the JPEG.
- Files carry **GPS coordinates** and device data. Catalogue them internally (useful for day/place grouping), strip them on every export.
- Typical clip lengths 10/20/30/45 s: the editor works in segments, not whole clips.

**Measured on real Day 01 footage (25 Nov 2026):** video is H.264 High, AAC 48 kHz stereo, stored at **2336×1080** (the phone's 19.5:9 mode) or 1920×1080, with display rotation −90 for portrait. Several clips are variable frame rate (average 28–29.9 fps against 30 nominal). Clip lengths ran from 0.8 s to 56 s, not only 10–45 s. Photos are 4000×1848 JPEG with EXIF Orientation 6. GPS was **not** present in the sampled files (location tagging appears off), which is good for privacy; the librarian still checks every file. 2336×1080 is wider than 16:9, so long-form exports need a crop or pad decision, and 9:16 Reels crop about 15% off each long edge.

## 5. Content lifecycle (state machine)

```
idea → planned → footage_selected → scripted → voiced → rough_cut → reviewed
     → thumbnail_ready → pending_approval ──approve──► approved → scheduled → published → measured
                               └──reject (with notes)──► back to the relevant earlier state
```

- Each transition is logged (`who`, `when`, `from`, `to`, `note`).
- `pending_approval → approved` can only be set by Harsh via dashboard or Telegram, never by an agent.
- Approval stores the SHA-256 of the exact video, caption text and thumbnail approved. Any change after approval drops it back to `pending_approval`.

## 6. Components

### 6.1 Core (`app/core/`)
Config loading (`config/*.yaml` + `.env`), path resolution and the write guard, structured logging to `logs/`, content ID generation, budget meter for paid API calls.

### 6.2 Provider layer (`app/providers/`)
A small interface so agents never touch an SDK directly:

- `LLMProvider.complete(role, messages, schema=None)` returns text or validated JSON.
- `VisionProvider.describe(images)` for frame tagging (later).
- `TTSProvider.synthesise(text, voice)` (later).

`config/providers.yaml` maps **roles** (e.g. `writer`, `planner`, `tagger`) to provider + model. Default provider is Anthropic Claude; OpenAI can be plugged in to reuse existing HARSHAD AI HQ keys. Every call is logged with token counts and cost estimate, and checked against the monthly budget cap. Confidential media is blocked at this layer: if a request references a `confidential` media ID, it fails before anything leaves the machine.

### 6.3 Database (`app/db/`, `db/`)
SQLite, WAL mode, single file `db/hq.sqlite3` (git-ignored). Initial tables (draft):

| Table | Key columns |
|---|---|
| `media` | id, rel_path, sha256, kind (video/photo/audio), duration_s, width, height, rotation, orientation, fps, codec, hdr, captured_at, gps_lat/lon (internal only), trip, day, privacy_class, tags, ingested_at |
| `content` | id (JD-R-003), series, format (reel/short/long), title, state, platform_targets, planned_date |
| `content_media` | content_id, media_id, in_s, out_s, order, role (a-roll/b-roll/still) |
| `assets` | id, content_id, kind (script/srt/voice/video/thumbnail/caption), path, sha256, version, recipe_json |
| `approvals` | id, content_id, asset_hashes, decision, note, decided_by, decided_at |
| `posts` | id, content_id, platform, platform_post_id, url, published_at |
| `metrics` | post_id, captured_at, views, reach, likes, comments, shares, saves, watch_time_s, avg_view_pct |
| `jobs` | id, type, payload_json, status, attempts, started_at, finished_at, log_path |
| `llm_calls` | id, role, provider, model, tokens_in, tokens_out, est_cost, created_at |
| `events` | id, entity, entity_id, from_state, to_state, actor, note, at |

Migrations: numbered SQL files in `db/migrations/` (`0001_init.sql`, …), applied in order and recorded in a `schema_version` table.

### 6.4 Media engine (`app/media/`)
Thin, logged wrappers over ffprobe/FFmpeg: `probe`, `make_proxy` (low-res H.264 for fast preview and AI frame sampling), `contact_sheet`, `trim`, `reframe` (9:16 ↔ 16:9 with blur-pad or crop), `concat`, `burn_subtitles`, `loudnorm` (two-pass, target about −14 LUFS for social), `export` (preset-driven, metadata stripped). Presets live in `config/render_presets.yaml`.

### 6.5 Orchestrator (`app/orchestrator/`)
A SQLite-backed job queue plus the content state machine. Runs jobs in a single worker process at first (renders are CPU/GPU-heavy; parallelism comes later if needed). Retries with backoff, never retries a publish automatically. Exposes a CLI (`hq run`, `hq status`) that n8n and the dashboard call.

### 6.6 Specialist agents (`app/agents/`)
Each agent is a Python module with: a clear input contract, an output contract (files + DB rows), and its prompts in `prompts/` as versioned text files. Agents don't call each other; the orchestrator sequences them.

| Agent | Does | Uses AI for | Deterministic part |
|---|---|---|---|
| Executive Producer | Series plan, content calendar, assigns jobs, assembles approval packages | Proposing calendar and angles from the catalogue | State transitions, packaging, scheduling |
| Media Librarian | Ingests and catalogues originals, groups by trip/day/place, flags duplicates and unusable clips | Tagging scenes from sampled frames (non-confidential only) | Hashing, ffprobe, proxies, privacy rules |
| Travel Storyteller | Story outline, script, captions, hashtags, titles, descriptions, subtitles | Writing in Harsh's voice, English with natural Marathi/Hindi | Length limits per platform, banned-claims check |
| Video Editor | Turns a script + selected media into an edit list and renders | Suggesting clip order and trims | FFmpeg render, reframing, subtitle burn-in |
| Voiceover & Audio Producer | Narration (Harsh's recorded voice first, TTS optional), music bed, ducking, loudness | Script-to-speech timing hints | Mixing, loudnorm, sync to edit list |
| Publisher | Final package, upload, schedule, record post IDs | Nothing by default | Approval check by hash, API calls, retries |
| Growth Analyst | Pulls metrics, weekly report, recommendations | Interpreting patterns, suggesting experiments | Metric collection, comparisons |

### 6.7 Dashboard (`app/dashboard/`)
Local web app on `localhost` (FastAPI + simple server-rendered pages is the working assumption; to be confirmed as a decision). Views: calendar, content board by state, review page (video player, script, caption, thumbnail side by side), approve/reject with notes, media browser with privacy badges. Telegram is the mobile companion: preview link + Approve / Reject buttons, which call the same approval endpoint.

### 6.8 Integrations (`app/integrations/`)
- **YouTube Data API v3** (OAuth, upload, thumbnails, analytics). Upload quota is limited per day, and uploads from an unverified API project may be forced to private until Google audits the project. Plan for that before relying on API uploads; manual upload of the approved package is the fallback.
- **Instagram Graph API** (content publishing for Reels). Needs an Instagram Professional account linked to a Facebook Page and a Meta app. Rate-limited.
- **Telegram Bot API** for notifications and approvals (free).
- **Google Drive/Sheets** optional: mirror the calendar or share approved packages.

Exact current limits and review requirements are to be verified at the time each integration is built.

## 7. Privacy and confidentiality model

| Class | Default for | Can go to external AI | Can be published |
|---|---|---|---|
| `public_ok` | Nothing by default | Yes | Yes, after approval |
| `family_private` | All trip media at ingest | Yes (frames/transcripts only, no faces sent unless Harsh enables it) | Only once Harsh marks it `public_ok` for that content piece |
| `confidential` | Everything under `Customer Visit - FNEI/` and any folder with a `.confidential` marker | **No** | **No** |

Rules defined in `config/privacy.yaml`. Additional checks before publish: GPS/device metadata stripped, no customer name or logo in caption/script, no number plates or room numbers in frame (manual checklist first, automated detection later), post-after-leaving delay for live locations.

## 8. Security and secrets

- `.env` holds keys (Anthropic, OpenAI, Telegram, Meta, Google OAuth). Git-ignored. `.env.example` shows names only.
- OAuth refresh tokens stored under `db/secrets/` (git-ignored) or Windows Credential Manager; never in YAML.
- n8n workflow exports in `n8n/workflows/` must have credentials stripped before commit.
- Logs never contain keys or full prompts with personal data; they record IDs and token counts.

## 9. Cost control

- No fixed subscriptions in v0.x. n8n self-hosted, SQLite, FFmpeg are free.
- Claude API is pay-per-use: `config/settings.yaml` sets `monthly_budget_usd` (default 0 until Harsh sets it, which means AI calls are blocked until then).
- Cheap model for tagging/bulk work, stronger model for scripts. Batch where possible, cache prompts.
- TTS, music libraries, n8n Cloud, a GPU box: each needs explicit approval with a cost estimate.

## 10. Build order (incremental)

1. Core + config + DB schema + path guard. CLI skeleton `hq`.
2. Media Librarian v1: ingest, probe, hash, proxies, privacy classes, catalogue report.
3. First Reel end-to-end, mostly manual: select clips → render a 9:16 Reel with subtitles and loudness → review in a simple HTML page.
4. Travel Storyteller v1 (scripts + captions via provider layer, with budget cap).
5. Audio Producer v1 (own-voice narration import, music bed, ducking).
6. Approval flow: dashboard v1 + Telegram buttons.
7. Executive Producer: calendar and state machine automation via n8n schedules.
8. Publisher: YouTube first (manual-upload fallback), then Instagram.
9. Growth Analyst: metrics pull + weekly report.
10. Long-form YouTube assembly, thumbnails generation, archive footage reuse.

## 11. Open questions for Harsh

1. Where does this live on your PC (for example `D:\Harshad Media HQ\`)? Is the media on the same drive?
2. Channel handles and language mix (English with Marathi/Hindi phrases, or bilingual subtitles)?
3. Narration: your own recorded voice, TTS, or text-only with music for the first Reels?
4. GPU on the PC (for faster HEVC decode/encode via NVENC)?
5. Is a private GitHub repo wanted for the code (media folders stay out of git)?
