# Media Librarian

**Mission:** Knows every original file: what, where, when, how long, which orientation, how usable, how private.

**Inputs:** 01_RAW_MEDIA (read-only).
**Outputs:** media rows, proxies and contact sheets in cache/, catalogue report.
**AI does:** Scene tags and short descriptions from sampled proxy frames (non-confidential only).
**Code does (deterministic):** SHA-256, ffprobe metadata, rotation/orientation, duplicate detection, privacy class from config/privacy.yaml, integrity re-check.
**Guardrails:** Never writes, renames or deletes in 01_RAW_MEDIA. Confidential frames never leave the machine.
**Status:** not implemented. Prompts will live in `prompts/` as versioned text files.
