# Instagram & YouTube Publisher

**Mission:** Gets approved content live, correctly, once.

**Inputs:** Approved package in 07_READY_TO_PUBLISH.
**Outputs:** Platform post, posts row, archive copy in 08.
**AI does:** Nothing by default.
**Code does (deterministic):** Verifies approval hashes match the files, uploads, sets thumbnail/caption, records IDs.
**Guardrails:** Refuses without a matching approval. Never auto-retries a publish. Manual-upload fallback.
**Status:** not implemented. Prompts will live in `prompts/` as versioned text files.
