# orchestrator
**Purpose:** SQLite-backed job queue + content state machine (idea → … → pending_approval → approved → published → measured). Sequences agents; agents never call each other. Only Harsh can move `pending_approval → approved`. Publish jobs are never auto-retried.
**Interface:** `hq` CLI (`hq run`, `hq status`) used by n8n and the dashboard.
**Status:** state machine and approval flow implemented (`state.py`, `approval.py`); job queue not yet.

**Approval flow (you run these on your PC):**
```
hq review                       # what exists and its state
hq submit JD-R-001              # latest render -> pending_approval
hq approve JD-R-001             # asks you each pre-publish checklist item, then to type the ID
hq reject JD-R-001 --note "drop the couple photo"
hq check JD-R-001               # is the approved package still exactly what you approved?
```
On approve, the video (plus `03_AI_SCRIPTS/<Series>/<id>/caption.txt` and `06_THUMBNAILS/<Series>/<id>/thumbnail.jpg` if present) is SHA-256 hashed, copied to `07_READY_TO_PUBLISH/<Series>/<id>/` with `manifest.json`, and recorded in `approvals`. Any later change, deletion or addition voids the approval and drops the content back to `pending_approval`.

**Guards:** only an actor `human:<os user>` can approve or reject; agent names are refused; approval needs the checklist confirmed; content using confidential media cannot be approved; every transition is in `events`.
