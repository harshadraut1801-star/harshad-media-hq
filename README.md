# Harshad Media HQ

AI-assisted travel content studio: raw phone footage in, approved Reels, Shorts and YouTube videos out.
Human approval at every public step.

**Status:** Foundation (structure, rules, architecture). No agents implemented yet.

## Quick map

```
Harshad Media HQ/
│
├── 01_RAW_MEDIA/            Originals from the Samsung S21 FE + archive. READ-ONLY.
│   ├── Jaipur Diaries/
│   │   ├── Day 01 - Aurangabad to Indore/
│   │   ├── Day 02 - Indore/
│   │   ├── Day 03 - Jaipur/
│   │   └── Customer Visit - FNEI/   CONFIDENTIAL — never auto-published
│   └── Previous Trips/
│
├── 02_SELECTED_FOOTAGE/     Chosen clips/stills per content piece (copies or trimmed renders)
├── 03_AI_SCRIPTS/           Story outlines, scripts, captions, subtitles (.md / .srt / .json)
├── 04_VOICEOVERS/           Narration audio, music beds, mixed stems
├── 05_EDITED_VIDEOS/        Rendered drafts: reels, shorts, long-form
├── 06_THUMBNAILS/           Thumbnail candidates and finals
├── 07_READY_TO_PUBLISH/     Approved packages (video + caption + thumbnail + metadata)
├── 08_PUBLISHED_CONTENT/    Archive of what went live, with post IDs and URLs
│
├── app/                     Python application (see below)
├── config/                  YAML settings: paths, providers, privacy, render presets
├── db/                      SQLite database + numbered migrations
├── docs/                    Architecture, decisions (ADRs), runbooks
├── n8n/workflows/           Exported n8n workflow JSON (no credentials inside)
├── scripts/                 One-off and setup scripts
├── tests/                   pytest suite (synthetic test media only)
├── cache/                   Proxies, contact sheets, temp renders (safe to delete)
├── logs/                    Run logs (safe to delete)
├── .env.example             Placeholder secrets — copy to .env, never commit .env
├── CLAUDE.md                Rules for AI assistants working here
└── README.md                This file
```

The numbered folders are the **production line**: a piece of content moves left to right, 02 → 08. Inside each stage folder, work is filed as `<Series>/<content_id>/`, e.g. `05_EDITED_VIDEOS/Jaipur Diaries/JD-R-003/`.

## Application components (`app/`)

| Folder | Role |
|---|---|
| `core/` | Config loader, path guard (blocks writes into 01_RAW_MEDIA), logging, IDs |
| `providers/` | LLM / TTS provider layer. Claude by default, others swappable via config |
| `db/` | SQLite access and models: media, content, approvals, posts, metrics |
| `media/` | ffprobe/FFmpeg wrappers: probe, proxy, trim, reframe, loudness, subtitles, export |
| `orchestrator/` | Job queue and content state machine; runs agents in order and enforces gates |
| `agents/executive_producer/` | Plans series and calendar, assigns work, owns the approval queue |
| `agents/media_librarian/` | Catalogues originals read-only: metadata, hashes, tags, privacy class |
| `agents/travel_storyteller/` | Story outlines, scripts, captions, hashtags, titles, subtitles |
| `agents/video_editor/` | Builds edit decision lists and renders via FFmpeg |
| `agents/audio_producer/` | Narration (own voice or TTS), music bed, ducking, loudness |
| `agents/publisher/` | Packages and (after approval) uploads to Instagram / YouTube |
| `agents/growth_analyst/` | Pulls metrics, reports, recommends changes |
| `dashboard/` | Local web UI: calendar, review, approve/reject with notes |
| `integrations/` | Meta Graph API, YouTube Data API, Telegram, Google Drive/Sheets |

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Setup (when the first component lands)

1. Install Python 3.11+, FFmpeg (includes ffprobe) and, later, n8n self-hosted (free; n8n Cloud is a paid plan and needs approval).
2. `python -m venv .venv` and `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in only the keys needed for the current task.
4. Set `MEDIA_ROOT` in `.env` to this folder's location on your PC.
5. Drop phone media into the right `01_RAW_MEDIA/` day folder. Don't rename the files; the system tracks them by hash.

## Rules in one breath

Originals untouched. Nothing published or paid for without Harsh's OK. FNEI customer footage is confidential. Keys stay in `.env`. Build one piece at a time and document it. Details in [`CLAUDE.md`](CLAUDE.md).
