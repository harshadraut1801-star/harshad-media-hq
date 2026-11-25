# config
- `settings.yaml` — paths (relative to MEDIA_ROOT), series, budget cap, publishing flags.
- `providers.yaml` — AI roles → provider + model. Change models here, not in code.
- `privacy.yaml` — privacy classes, confidential folders, export metadata stripping, pre-publish checklist.
- `render_presets.yaml` — FFmpeg presets for reel / short / long.
No secrets in this folder. Secrets go in `.env`.
