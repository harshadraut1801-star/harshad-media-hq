# Video Editor

**Mission:** Cuts the Reel / Short / long video.

**Inputs:** Script, selected media, voiceover, render preset.
**Outputs:** Edit decision list (JSON), clips in 02, renders in 05.
**AI does:** Suggest clip order, in/out points, b-roll matching to script lines.
**Code does (deterministic):** FFmpeg renders: reframe, concat, subtitles, transitions, loudness, metadata strip.
**Guardrails:** Reads originals only; output always outside 01.
**Status:** v1 implemented (render from a hand- or Claude-written edit list; AI clip suggestions not yet).

**Use:**
```
hq render "02_SELECTED_FOOTAGE/Jaipur Diaries/JD-R-001/edl.yaml"
```
Output in `05_EDITED_VIDEOS/<Series>/<id>/`: `<id>_vN.mp4`, `<id>_vN.json` (manifest: sources, trims, SHA-256, every FFmpeg command) and `<id>_vN_review.html` (player + shot list + pre-publish checklist). Each render makes a new version; older versions are kept.

**EDL format:** see the docstring in `edl.py`. Per segment: `src` (relative to MEDIA_ROOT), `in`/`out` for clips or `duration` for photos, `frame: cover|fit`, `focus_x` (0–1, which part of a landscape frame to keep), `caption`.

**Pipeline:** per-segment normalise (reframe to 1080×1920, CFR 30 fps, yuv420p, 48 kHz stereo, 0.2 s fade at cuts; photos EXIF-rotated and given a slow zoom) → lossless concat → captions (ASS, kept above the platform UI) + two-pass loudnorm (−20 LUFS for ambient-only, −14 with voice/music later) + H.264 High/AAC, metadata stripped. Presets in `config/render_presets.yaml`.

**Guards:** confidential sources are refused; trims past the clip end are refused; originals are only FFmpeg inputs; outputs go through the path guard; content/asset/event rows record what was made.

**Not yet:** music/voiceover mixing (Audio Producer), smart crop that follows the subject, plate/face blurring, transitions beyond dip-to-black.
