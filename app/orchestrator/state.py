"""Content lifecycle state machine. Every transition is written to `events`.

    idea -> planned -> footage_selected -> scripted -> voiced -> rough_cut
         -> pending_approval -> approved -> scheduled -> published -> measured
    pending_approval -> rejected -> (any working state, after changes)
    approved -> pending_approval   (automatically, if an approved file changes)

Only a human may move pending_approval -> approved or -> rejected. Agents pass
their own name as actor and are refused.
"""
from __future__ import annotations

WORKING = ("idea", "planned", "footage_selected", "scripted", "voiced", "rough_cut")
STATES = (*WORKING, "pending_approval", "approved", "rejected", "scheduled", "published", "measured")

ALLOWED: dict[str, set[str]] = {
    **{s: set(WORKING) | {"pending_approval"} for s in WORKING},
    "pending_approval": {"approved", "rejected", *WORKING},
    "rejected": set(WORKING) | {"pending_approval"},
    "approved": {"scheduled", "pending_approval", *WORKING},
    "scheduled": {"published", "approved", "pending_approval"},
    "published": {"measured"},
    "measured": {"measured"},
}
HUMAN_ONLY = {("pending_approval", "approved"), ("pending_approval", "rejected")}
AGENT_ACTORS = {"executive_producer", "media_librarian", "travel_storyteller", "video_editor",
                "audio_producer", "publisher", "growth_analyst", "system"}


class TransitionError(RuntimeError):
    pass


def current_state(conn, content_id: str) -> str:
    row = conn.execute("SELECT state FROM content WHERE id=?", (content_id,)).fetchone()
    if row is None:
        raise TransitionError(f"Unknown content: {content_id}")
    return row[0]


def transition(conn, content_id: str, to_state: str, *, actor: str, note: str | None = None) -> str:
    if to_state not in STATES:
        raise TransitionError(f"Unknown state: {to_state}")
    frm = current_state(conn, content_id)
    if to_state not in ALLOWED.get(frm, set()):
        raise TransitionError(f"{content_id}: cannot go from {frm} to {to_state}")
    if (frm, to_state) in HUMAN_ONLY and (actor in AGENT_ACTORS or not actor.startswith("human:")):
        raise TransitionError(f"{content_id}: only a person can {to_state.replace('_', ' ')} content")
    conn.execute("UPDATE content SET state=? WHERE id=?", (to_state, content_id))
    conn.execute("INSERT INTO events (entity, entity_id, from_state, to_state, actor, note) VALUES "
                 "('content', ?, ?, ?, ?, ?)", (content_id, frm, to_state, actor, note))
    conn.commit()
    return frm
