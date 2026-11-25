# core
**Purpose:** shared plumbing. Config loader (`config/*.yaml` + `.env`), path resolution, the **write guard** that refuses any write into `01_RAW_MEDIA`, structured logging, content ID generator (`JD-R-###`), budget meter for paid API calls.
**Inputs:** config files, environment. **Outputs:** settings object, logger, safe paths.
**Status:** v0.1 implemented.
- `config.py`: `load_settings()` reads `config/*.yaml` + `.env`; `MEDIA_ROOT` may point to another drive. Secrets are kept out of `repr()`.
- `paths.py`: `safe_write_path()` / `open_for_write()` refuse any target resolving inside `01_RAW_MEDIA` (handles `..`, symlinks, Windows case). **Every writer must use these.**
- `privacy.py`: `classify()` gives `confidential` for configured paths or folders holding `.confidential`, else the default class.
- `logging.py`: console + `logs/hq-YYYY-MM-DD.log`.
- `ids.py`: `next_content_id(conn, "JD", "reel")` gives `JD-R-001`, etc.
Not yet: Windows read-only attribute on 01_RAW_MEDIA (optional, later).
