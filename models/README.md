# models

Offline model files used by the app. No network calls at runtime.

| File | Use | Source | Licence | SHA-256 |
|---|---|---|---|---|
| `face_detection_yunet_2023mar.onnx` | face detection for blurring (`app/media/privacy_blur.py`) | OpenCV Zoo, `models/face_detection_yunet` | MIT (Shiqi Yu) | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |

There is no reliable free, offline number-plate detector bundled here. Plates are blurred with manual boxes in the edit list, and `hq privacy-scan` gives you a frame grid to check by eye.
