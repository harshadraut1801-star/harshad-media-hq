# Voiceover & Audio Producer

**Mission:** Makes it sound good: narration, music, levels.

**Inputs:** Script, edit list, Harsh's recorded narration or TTS (TTS needs approval if paid).
**Outputs:** Narration takes, music bed, final mix in 04.
**AI does:** Timing hints for script-to-speech; TTS only if approved.
**Code does (deterministic):** Noise reduction, ducking music under voice, two-pass loudnorm to target LUFS.
**Guardrails:** Only licence-clear music. No paid library or TTS without approval.
**Status:** not implemented. Prompts will live in `prompts/` as versioned text files.
