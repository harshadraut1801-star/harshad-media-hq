# core
**Purpose:** shared plumbing. Config loader (`config/*.yaml` + `.env`), path resolution, the **write guard** that refuses any write into `01_RAW_MEDIA`, structured logging, content ID generator (`JD-R-###`), budget meter for paid API calls.
**Inputs:** config files, environment. **Outputs:** settings object, logger, safe paths.
**Status:** not implemented (next task #1).
