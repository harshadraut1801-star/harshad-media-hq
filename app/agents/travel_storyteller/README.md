# Travel Storyteller

**Mission:** Turns footage and trip facts into a story people finish watching.

**Inputs:** Selected media + tags, trip notes from Harsh, platform format.
**Outputs:** Outline, script, captions, hashtags, titles, descriptions, .srt in 03_AI_SCRIPTS.
**AI does:** Writing in Harsh's voice (English with natural Marathi/Hindi), hooks, title options.
**Code does (deterministic):** Platform length limits, subtitle timing, banned-claims and privacy-term check (customer names, plates, room numbers).
**Guardrails:** No invented facts about places, family, business or customers.
**Status:** not implemented. Prompts will live in `prompts/` as versioned text files.
