"""Privacy scan of a rendered video: a frame grid for a final eyeball check.

Samples frames (default 2 per second), runs offline face detection, and writes
<video>_privacy.html next to the video: every sampled frame with its timestamp,
detected faces boxed in red. Number plates, stickers, house numbers and
documents can't be detected reliably for free, so the page asks you to look.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

from app.core.config import Settings
from app.core.paths import open_for_write


def scan_video(settings: Settings, video: Path, per_second: float = 2.0) -> tuple[Path, int, int]:
    import cv2

    from app.media.privacy_blur import FaceDetector

    det = FaceDetector()
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps / per_second)))
    tiles, idx, face_frames = [], 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            faces = det.detect(frame)
            for x, y, w, h, _ in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 6)
            face_frames += bool(faces)
            h0, w0 = frame.shape[:2]
            small = cv2.resize(frame, (240, int(240 * h0 / w0)))
            ok2, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
            tiles.append((idx / fps, len(faces), base64.b64encode(jpg.tobytes()).decode()))
        idx += 1
    cap.release()
    out = video.with_name(video.stem + "_privacy.html")
    cells = "".join(
        f"<figure class='{'f' if n else ''}'><img src='data:image/jpeg;base64,{b}'>"
        f"<figcaption>{t:.1f}s{' · ' + str(n) + ' face(s)' if n else ''}</figcaption></figure>"
        for t, n, b in tiles)
    doc = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy scan</title>
<style>:root{{--bg:#f6f5f2;--fg:#1d1d1b;--warn:#b42318}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe8;--warn:#f97066}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0;padding:16px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}}
figure{{margin:0}} img{{width:100%;border-radius:6px;display:block}} figcaption{{font-size:12px}}
.f figcaption{{color:var(--warn);font-weight:700}}</style>
<h1>Privacy scan: {html.escape(video.name)}</h1>
<p>{len(tiles)} frames sampled, faces found in {face_frames}. Red boxes are faces the blur step would hide.</p>
<p><b>Check by eye:</b> number plates (including on stickers and the backs of trucks), house or room numbers,
documents and screens, customer names or logos, anything showing where you are right now.</p>
<div class="g">{cells}</div>"""
    with open_for_write(settings, out) as fh:
        fh.write(doc)
    return out, len(tiles), face_frames
