# providers
**Purpose:** the only place that talks to AI vendors. Agents request a *role* (`writer`, `tagger`, `planner`…); `config/providers.yaml` maps it to provider + model. Claude is default; OpenAI optional.
**Guards:** budget cap check before every call; refuses any request that references `confidential` media; logs tokens and estimated cost to `llm_calls`.
**Interfaces (planned):** `LLMProvider.complete()`, `VisionProvider.describe()`, `TTSProvider.synthesise()`.
**Status:** v0.1 interface implemented in `base.py`: `LLMProvider.complete()` runs the confidential-media guard and the budget guard, then logs the call to `llm_calls`. `DryRunProvider` (free, offline) is the only registered provider. Roles in `providers.yaml` still point at `anthropic`, so `get_provider()` gives a clear "not implemented yet" error until the Anthropic provider lands with the Storyteller task. Vision and TTS interfaces come later.
