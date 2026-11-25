# Media Librarian

**Mission:** Knows every original file: what, where, when, how long, which orientation, how usable, how private.

**Inputs:** 01_RAW_MEDIA (read-only).
**Outputs:** media rows, proxies and contact sheets in cache/, catalogue report.
**AI does:** Scene tags and short descriptions from sampled proxy frames (non-confidential only).
**Code does (deterministic):** SHA-256, ffprobe metadata, rotation/orientation, duplicate detection, privacy class from config/privacy.yaml, integrity re-check.
**Guardrails:** Never writes, renames or deletes in 01_RAW_MEDIA. Confidential frames never leave the machine.
**Status:** v1 implemented (no AI yet).

**Use:**
```
hq scan                      # whole 01_RAW_MEDIA, thumbnails on
hq scan --path "Jaipur Diaries/Day 01 - Aurangabad to Indore"
hq scan --proxies            # also 540p CFR proxies in cache/proxies (slow on 4K)
hq verify                    # re-hash every original, report changed/missing
hq catalogue                 # summary + cache/reports/catalogue.html
hq privacy-scan <video>      # frame grid with faces boxed in red, written next to the video
```

**Per file:** SHA-256 (opened read-only), ffprobe/EXIF metadata, true orientation (rotation applied), duration, fps, VFR/HDR flags, capture time (UTC), GPS (stored internally only), camera model, Samsung Motion Photo detection, series/day from folder, privacy class, duplicate-by-hash, thumbnail.

**Rules it keeps:** never writes, renames or deletes in 01_RAW_MEDIA; archives (.zip etc.) are reported and not opened; a changed original is flagged `changed` with the original hash kept; a vanished one is flagged `missing`. Re-scans skip files whose size and mtime are unchanged. The HTML report shows no thumbnail for confidential files and never shows GPS.

**Not yet:** AI scene tagging from proxy frames (non-confidential only, needs budget), usability scoring (shake/blur), number-plate detection (faces are done, see `hq privacy-scan`).
