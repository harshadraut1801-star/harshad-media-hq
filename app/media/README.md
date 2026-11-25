# media
**Purpose:** thin, logged wrappers over ffprobe/FFmpeg: probe, proxy, contact sheet, trim, reframe (blur-pad / crop), concat, burn subtitles, two-pass loudnorm, preset export with metadata stripped.
**Handles S21 FE quirks:** rotation flags, HEVC, HDR10+ tone-mapping, variable frame rate, Motion Photos, GPS metadata.
**Status:** `probe.py` (video via ffprobe, photo via Pillow EXIF) and `thumbs.py` (thumbnail, 540p proxy, metadata stripped) implemented. Rendering lives in `app/agents/video_editor/render.py`. `privacy_blur.py` (task 5): offline YuNet face detection (`models/`), pixelate faces in photos and videos (OpenCV frames piped to FFmpeg, audio copied back).
