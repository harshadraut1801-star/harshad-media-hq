# Video Editor

**Mission:** Cuts the Reel / Short / long video.

**Inputs:** Script, selected media, voiceover, render preset.
**Outputs:** Edit decision list (JSON), clips in 02, renders in 05.
**AI does:** Suggest clip order, in/out points, b-roll matching to script lines.
**Code does (deterministic):** FFmpeg renders: reframe, concat, subtitles, transitions, loudness, metadata strip.
**Guardrails:** Reads originals only; output always outside 01.
**Status:** not implemented. Prompts will live in `prompts/` as versioned text files.
