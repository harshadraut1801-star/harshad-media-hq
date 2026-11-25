# providers
**Purpose:** the only place that talks to AI vendors. Agents request a *role* (`writer`, `tagger`, `planner`…); `config/providers.yaml` maps it to provider + model. Claude is default; OpenAI optional.
**Guards:** budget cap check before every call; refuses any request that references `confidential` media; logs tokens and estimated cost to `llm_calls`.
**Interfaces (planned):** `LLMProvider.complete()`, `VisionProvider.describe()`, `TTSProvider.synthesise()`.
**Status:** not implemented (next task #1, interface + a dry-run provider; real Claude calls come with the Storyteller).
