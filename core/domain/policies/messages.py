"""Canonical message-turn classification shared across the session subsystem.

Two message spaces exist and MUST agree on what counts as a "real user turn":

* Transcript events (``AgentSession.messages``) — UI-shaped dicts with ``type``.
* Agent history entries (provider ``history``) — role/content chat messages.

Rewind, fork, git-checkpoint indexing and persistence all map UI-visible turn
positions onto these spaces. Every walk over either space must go through this
module so the index spaces cannot silently diverge.

Wire format for synthetic user messages (system-generated, never user-typed).
There is exactly ONE canonical form for each message type — no version
attribute, no legacy variants:

- ``<system_note kind="..." attrs>...</system_note>`` — runtime annotations
  (interruption, vision fallback, queue arrival, etc.). ``kind`` is a closed
  enum; unknown kinds are emitted but the model is told to treat any
  system_note as informational. The body and all attributes are XML-escaped
  so a tool result containing literal ``</system_note>`` cannot truncate the
  wrapper.
- ``<notification type="shell|subagent" id="..." title="..." status="..." truncated="..." duration_ms="...">...</notification>`` —
  background-task completions. The body is XML-escaped to prevent wrapper
  truncation by injection.
- ``<compaction_checkpoint>...</compaction_checkpoint>`` — historical context
  handoff (see core/base_provider/compaction.py). Unversioned is the only
  form; the parser strictly refuses malformed bodies.

All three are HIDDEN from the UI (TRANSCRIPT_HIDDEN_PREFIXES) and excluded
from real-user-turn counts. They are also dropped from compaction's
preserved-user-messages list so they don't pollute the next summary.
"""

from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# Transcript events (session.messages)
# ---------------------------------------------------------------------------

USER_EVENT_TYPE = "user"

TRANSCRIPT_HIDDEN_PREFIXES = (
    "<system_note",
    "<notification",
    "<compaction_checkpoint",
)
STALE_NOTE_PREFIX = (
    "<system_note",
)


# ---------------------------------------------------------------------------
# Wire format constants for synthetic user messages
# ---------------------------------------------------------------------------

# Canonical kinds for <system_note kind="...">. Adding a new kind means
# updating both this list AND the system prompt's <context> block so the
# model knows what to do with it.
SYSTEM_NOTICE_KIND_INTERRUPTED = "interrupted"
SYSTEM_NOTICE_KIND_IMAGES_OMITTED = "images_omitted"
SYSTEM_NOTICE_KIND_VISION_UNSUPPORTED = "vision_unsupported"
SYSTEM_NOTICE_KIND_RATE_LIMITED = "rate_limited"
SYSTEM_NOTICE_KIND_CONTEXT_TRIMMED = "context_trimmed"
SYSTEM_NOTICE_KIND_QUEUE_ARRIVED = "queue_arrived"
SYSTEM_NOTICE_KIND_PROVIDER_RECOVERED = "provider_recovered"
SYSTEM_NOTICE_KIND_TOOL_RESULT_LOST = "tool_result_lost"

NOTIFICATION_KIND_SHELL = "shell"
NOTIFICATION_KIND_SUBAGENT = "subagent"


def _xml_escape(s: Any) -> str:
    """Strict XML attribute/text escape for synthetic-message payloads.

    Used for every value that lands inside a synthetic-message body or
    attribute. Without this, a subagent report containing literal
    `</notification>` would truncate the wrapper and inject a
    prompt-injection surface.
    """
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def format_system_note(kind: str, body: str, **attrs: Any) -> str:
    """Build a ``<system_note>`` synthetic user message.

    The kind is mandatory; it tells the model (and our parsers) what the
    note means so the system prompt can enumerate behavior per kind.
    The kind attribute discriminates; the system prompt instructs the
    model to treat any system_note as informational, not actionable.

    Attributes (optional): when, what, model, path, etc. — caller
    decides what context is useful. Keep them terse.
    """
    kind_clean = _xml_escape(kind or "info")
    attr_str = ""
    for k, v in attrs.items():
        if v is None or v == "":
            continue
        attr_str += f' {k}="{_xml_escape(v)}"'
    body_clean = _xml_escape(body or "")
    return f"<system_note kind=\"{kind_clean}\"{attr_str}>{body_clean}</system_note>"


def format_background_notification(
    type_: str,
    title: str,
    task_id: str,
    result: str,
    *,
    status: str = "completed",
    truncated: bool = False,
    duration_ms: Optional[int] = None,
    event: Optional[str] = None,
    idle_seconds: Optional[int] = None,
) -> str:
    """Build a ``<notification>`` synthetic user message.

    Emitted as a synthetic user message when a background shell or
    subagent finishes or emits progress. The result body is XML-escaped so
    a subagent report containing ``</notification>`` cannot truncate the wrapper.

    Attributes:
        type:   "shell" | "subagent"
        id:     task_id / subagent session_id
        title:  human label
        status: "completed" | "cancelled" | "error" | "running"
        truncated: True iff result was capped; full result in companion log
        duration_ms: optional wall-clock time
        event: optional progress event ("inactivity", etc.)
        idle_seconds: optional silence duration in seconds
    """
    t_clean = _xml_escape(type_)
    title_clean = _xml_escape(title)
    id_clean = _xml_escape(task_id)
    status_clean = _xml_escape(status)
    duration_attr = f' duration_ms="{int(duration_ms)}"' if duration_ms is not None else ""
    trunc_attr = ' truncated="true"' if truncated else ""
    event_attr = f' event="{_xml_escape(event)}"' if event else ""
    idle_attr = f' idle_seconds="{int(idle_seconds)}"' if idle_seconds is not None else ""
    body_clean = _xml_escape(result)
    return (
        f'<notification type="{t_clean}" '
        f'id="{id_clean}" title="{title_clean}" '
        f'status="{status_clean}"{duration_attr}{trunc_attr}{event_attr}{idle_attr}>'
        f"{body_clean}"
        f"</notification>"
    )


# ---------------------------------------------------------------------------
# Classification helpers (unchanged behavior, more robust markers)
# ---------------------------------------------------------------------------

def is_ui_visible_user_message(msg: Any) -> bool:
    """True if a transcript event should be rendered/counted as a user turn."""
    if not isinstance(msg, dict):
        return False
    if msg.get("type") != USER_EVENT_TYPE:
        return False
    if msg.get("show_in_ui") is False:
        return False
    text = str(msg.get("text", ""))
    return not text.startswith(TRANSCRIPT_HIDDEN_PREFIXES)


def find_visible_user_cutoff(messages: List[Any], seq_idx: int) -> Optional[int]:
    """Index of the ``seq_idx``-th visible user turn (0-based over visible turns).

    Returns None when the transcript contains fewer visible turns.
    """
    visible = 0
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("type") != USER_EVENT_TYPE:
            continue
        if not is_ui_visible_user_message(msg):
            continue
        if visible == seq_idx:
            return idx
        visible += 1
    return None


def drop_stale_system_notes(messages: List[Any]) -> List[Any]:
    """Drop interruption notes that are not real user turns from a kept prefix."""
    return [
        m
        for m in messages
        if not (
            isinstance(m, dict)
            and m.get("type") == USER_EVENT_TYPE
            and str(m.get("text", "")).startswith(STALE_NOTE_PREFIX)
        )
    ]


def transcript_before_turn(messages: List[Any], seq_idx: int) -> List[Any]:
    """Transcript prefix strictly before the ``seq_idx``-th visible user turn.

    Stale interruption notes are dropped from the kept prefix. If the requested
    turn does not exist (fork of the full session), the whole note-filtered
    transcript is returned.
    """
    cutoff = find_visible_user_cutoff(messages, seq_idx)
    kept = messages if cutoff is None else messages[:cutoff]
    return drop_stale_system_notes(kept)


# ---------------------------------------------------------------------------
# Agent history entries (provider history)
# ---------------------------------------------------------------------------

# Compaction embeds summaries into history as fake user messages. There is
# exactly one canonical form — the walker just looks for the tag prefix.
HISTORY_NOTE_PREFIX = (
    "<system_note",
    "<notification",
)


def is_checkpoint_message(msg: Any) -> bool:
    """True if a history entry is a compaction checkpoint.

    A checkpoint is any user message whose content opens with the canonical
    ``<compaction_checkpoint>`` tag. The body parsing is the compactor's job
    (see core/base_provider/compaction.py); this function is a cheap prefix
    check used by the turn counters and rewind walk.
    """
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return content.startswith("<compaction_checkpoint>")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                text = str(part.get("text", ""))
                if text.startswith("<compaction_checkpoint>"):
                    return True
    return False


def is_system_note(msg: Any) -> bool:
    """True if a history entry is a synthetic system note (e.g. interruption)."""
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    return isinstance(content, str) and content.startswith(HISTORY_NOTE_PREFIX)


def is_real_history_user_turn(msg: Any) -> bool:
    """True if a history entry is a real user turn (not checkpoint/note)."""
    if not isinstance(msg, dict) or msg.get("role") != USER_EVENT_TYPE:
        return False
    return not is_checkpoint_message(msg) and not is_system_note(msg)


def find_history_user_cutoff(history: List[Any], seq_idx: int) -> Optional[int]:
    """Index of the ``seq_idx``-th real user turn in history, or None."""
    count = 0
    for idx, msg in enumerate(history):
        if not is_real_history_user_turn(msg):
            continue
        if count == seq_idx:
            return idx
        count += 1
    return None


def count_history_user_turns(history: List[Any]) -> int:
    """Number of real user turns in history (the rewritable tail length)."""
    return sum(1 for msg in history if is_real_history_user_turn(msg))


def history_before_turn(history: List[Any], seq_idx: int) -> List[Any]:
    """History prefix strictly before the ``seq_idx``-th real user turn.

    If the requested turn does not exist (fork of the full session), the whole
    history is returned.
    """
    cutoff = find_history_user_cutoff(history, seq_idx)
    if cutoff is None:
        return list(history)
    return history[:cutoff]

