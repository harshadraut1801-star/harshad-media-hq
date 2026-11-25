# 0002 — Privacy blur runs locally: manual plate boxes, opt-in face blur

Date: 2026-11-25. Status: accepted.

## Context
Public Reels must not show vehicle number plates, children's faces without consent, or other identifying details (CLAUDE.md rule 4). The AI budget is $0, so no paid vision API. Tested on the real Day 01 footage:
- OpenCV Haar plate cascade: misses Indian plates and fires on truck art. Not usable.
- Haar face cascade: false positives on road scenes.
- YuNet (OpenCV Zoo, MIT, 230 KB ONNX): found every face in the test frames with no false positives on car/road frames.

## Decision
- Faces: YuNet, offline, model file committed in `models/`. Off by default; `blur_faces: true` per EDL or per segment. Whether family faces are shown is a per-piece human decision.
- Plates and other text: manual boxes in the EDL (`blur:`), source-frame fractions with optional time range.
- Safety net: `hq privacy-scan` frame grid, checked by eye before `hq submit`.
- opencv-python-headless pinned below 5 (5.x drops the bundled cascades and changed APIs).

## Consequences
No running cost and nothing leaves the PC. Plate blurring depends on a human spotting plates; the scan report and the pre-publish checklist make that step explicit. Revisit if a good free plate detector appears or the budget allows a vision model.
