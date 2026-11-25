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

**Cover / thumbnail (task 6, local, free):**
```
hq covers JD-R-001                     # 12 candidate frames from the latest render + candidates.html contact sheet
hq cover JD-R-001 --t 11.2 --title "Day 01: Aurangabad to Indore" --subtitle "Jaipur Diaries"
```
- Candidates come from the *rendered* video, so plate boxes and face blur are already applied. Scored on sharpness, exposure, colour and faces; frames with a burned-in caption score lower. They are spread out in time and must look different from each other.
- `hq cover` writes `06_THUMBNAILS/<Series>/<id>/cover_vN.jpg` (+ `.json` recipe), `thumbnail.jpg` (what `hq submit/approve` package) and `grid_preview.jpg` (the 3:4 centre crop Instagram's profile grid shows; the title is placed inside it). Format follows the content (reel/short 1080×1920, long 1280×720) or `--format`.
- The title is always your text; nothing is generated. No EXIF/metadata in any output. Confidential content is refused. Font: `cover.font` in `render_presets.yaml` (Arial Bold on Windows; DejaVu Sans Bold fallback).
- Changing `thumbnail.jpg` after approval voids the approval (`hq check`), as it should.

**EDL format:** see the docstring in `edl.py`. Per segment: `src` (relative to MEDIA_ROOT), `in`/`out` for clips or `duration` for photos, `frame: cover|fit`, `focus_x` (0–1, which part of a landscape frame to keep), `caption`, `blur` (list of boxes, see below), `blur_faces` (true/false, overrides the top-level `blur_faces`).

**Privacy blur (task 5, all local, free):**
- Number plates, house numbers, room numbers: add manual boxes per segment, as fractions of the *output* 1080×1920 frame (what you see in the draft, top-left = 0,0): `blur: [{x: 0.62, y: 0.555, w: 0.20, h: 0.065, from: 0, to: 1.5}]` (`from`/`to` in seconds of the segment, optional). Boxes are pixelated (28 px blocks) + blurred in the render; large text like a windscreen sticker is unreadable, not just softened. There is no reliable free plate detector, so plates are always a human call.
- Faces: `blur_faces: true` at the top of the EDL (whole reel) or per segment. Uses the offline YuNet detector (`models/`), pads each box by 35 % and holds it for 6 frames so blur doesn't flicker. Off by default because most shots are of the family, who may want to be seen; it is Harsh's choice per piece.
- After rendering, run `hq privacy-scan <video>`: it samples 2 frames/s, draws red boxes where faces are still visible, and lists frames to check by eye for plates. Do this before `hq submit`.
- The manifest records `blur_faces`, `faces_blurred` and `blur_boxes` per segment; the review page has a Blur column.

**Pipeline:** per-segment normalise (reframe to 1080×1920, CFR 30 fps, yuv420p, 48 kHz stereo, 0.2 s fade at cuts; photos EXIF-rotated and given a slow zoom) → lossless concat → captions (ASS, kept above the platform UI) + two-pass loudnorm (−20 LUFS for ambient-only, −14 with voice/music later) + H.264 High/AAC, metadata stripped. Presets in `config/render_presets.yaml`.

**Guards:** confidential sources are refused; trims past the clip end are refused; originals are only FFmpeg inputs; outputs go through the path guard; content/asset/event rows record what was made.

**Not yet:** music/voiceover mixing (Audio Producer), smart crop that follows the subject, automatic plate detection, transitions beyond dip-to-black.
