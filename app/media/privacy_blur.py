"""Local, offline face blurring with OpenCV YuNet, plus helpers for manual boxes.

- Faces: YuNet (models/face_detection_yunet_2023mar.onnx, MIT). Detected boxes are
  grown by 35% and pixelated, so the result can't be undone by sharpening.
  In video, a box is held for a few frames after detection drops out, so a
  face doesn't flash through on a missed frame.
- Number plates: no reliable free detector exists, so plates are blurred with
  manual boxes from the edit list (see render.py) and checked with privacy-scan.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

MODEL = Path(__file__).resolve().parents[2] / "models" / "face_detection_yunet_2023mar.onnx"
DETECT_LONG_SIDE = 960
SCORE = 0.6
GROW = 0.35
HOLD_FRAMES = 6


def _cv2():
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("OpenCV not installed: pip install -e .[dev]") from exc
    return cv2


class FaceDetector:
    def __init__(self, score: float = SCORE):
        cv2 = _cv2()
        if not MODEL.is_file():
            raise RuntimeError(f"Face model missing: {MODEL}")
        self._cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(str(MODEL), "", (320, 320), score, 0.3, 5000)

    def detect(self, bgr: np.ndarray) -> list[tuple[int, int, int, int, float]]:
        """Boxes (x, y, w, h, score) in the input image's pixels."""
        h, w = bgr.shape[:2]
        scale = min(1.0, DETECT_LONG_SIDE / max(h, w))
        small = self._cv2.resize(bgr, (int(w * scale), int(h * scale))) if scale < 1 else bgr
        self._det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self._det.detect(small)
        if faces is None:
            return []
        return [(int(f[0] / scale), int(f[1] / scale), int(f[2] / scale), int(f[3] / scale), float(f[-1]))
                for f in faces]


def grow(box, w_img, h_img, factor=GROW):
    x, y, w, h = box[:4]
    dx, dy = int(w * factor / 2), int(h * factor / 2)
    x0, y0 = max(0, x - dx), max(0, y - dy)
    x1, y1 = min(w_img, x + w + dx), min(h_img, y + h + dy)
    return x0, y0, x1 - x0, y1 - y0


def pixelate(bgr: np.ndarray, box) -> None:
    """In-place mosaic of a region (about 8 blocks across), then a light blur."""
    cv2 = _cv2()
    x, y, w, h = box
    if w < 2 or h < 2:
        return
    roi = bgr[y:y + h, x:x + w]
    blocks = max(2, min(8, w // 4))
    small = cv2.resize(roi, (blocks, max(2, blocks * h // max(w, 1))), interpolation=cv2.INTER_LINEAR)
    mosaic = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    k = max(3, (min(w, h) // 6) | 1)
    bgr[y:y + h, x:x + w] = cv2.GaussianBlur(mosaic, (k, k), 0)


def blur_faces_image(bgr: np.ndarray, detector: FaceDetector | None = None) -> int:
    detector = detector or FaceDetector()
    h, w = bgr.shape[:2]
    faces = detector.detect(bgr)
    for f in faces:
        pixelate(bgr, grow(f, w, h))
    return len(faces)


def blur_faces_video(src: Path, dst: Path, fps: int = 30) -> int:
    """Read src frame by frame, pixelate faces, write dst (H.264, audio copied as PCM).
    Returns the number of frames that had at least one face."""
    cv2 = _cv2()
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")
    cap = cv2.VideoCapture(str(src))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    tmp_video = dst.with_suffix(".noaudio.mkv")
    enc = subprocess.Popen([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                            "-pix_fmt", "yuv420p", str(tmp_video)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    det = FaceDetector()
    held: list[tuple[tuple[int, int, int, int], int]] = []
    hit_frames = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            faces = det.detect(frame)
            boxes = [grow(f, w, h) for f in faces]
            held = [(b, HOLD_FRAMES) for b in boxes] + [(b, n - 1) for b, n in held if n > 1 and not boxes]
            for b, _ in held:
                pixelate(frame, b)
            if faces:
                hit_frames += 1
            enc.stdin.write(frame.tobytes())
    finally:
        cap.release()
        enc.stdin.close()
        err = enc.stderr.read().decode(errors="replace")
        enc.wait()
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {err[-300:]}")
    proc = subprocess.run([ff, "-v", "error", "-y", "-i", str(tmp_video), "-i", str(src), "-map", "0:v", "-map",
                           "1:a?", "-c:v", "copy", "-c:a", "pcm_s16le", "-shortest", str(dst)],
                          capture_output=True, text=True)
    tmp_video.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {proc.stderr[-300:]}")
    return hit_frames
