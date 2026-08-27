"""Canonical message-turn classification shared across the session subsystem.

Two message spaces exist and MUST agree on what counts as a "real user turn":

* Transcript events (``AgentSession.messages``) — UI-shaped dicts with ``type``.
* Agent history entries (provider ``history``) — role/content chat messages.

Rewind, fork, git-checkpoint indexing and persistence all map UI-visible turn
positions onto these spaces. Every walk over either space must go through this
module so the index spaces cannot silently diverge.
"""

from typing import Any, List, Optional

# ---------------------------------------------------------------------------
# Transcript events (session.messages)
# ---------------------------------------------------------------------------

USER_EVENT_TYPE = "user"

TRANSCRIPT_HIDDEN_PREFIXES = (
    "[System Notification]",
    "[System Note:",
    "<system_note",
    "<notification",
    "<task_notification",
    "<system_notification",
)
STALE_NOTE_PREFIX = (
    "[System Note:",
    "<system_note",
)


def is_ui_visible_user_message(msg: Any) -> bool:
    """True if a transcript event should be rendered/counted as a user turn."""
    if not isinstance(msg, dict):
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

# Compaction embeds summaries into history as fake user messages.
HISTORY_CHECKPOINT_MARKERS = ("<conversation_checkpoint>", "<summary>")
HISTORY_NOTE_PREFIX = (
    "[System Note:",
    "<system_note",
    "<notification",
    "<task_notification",
    "<system_notification",
)


def is_checkpoint_message(msg: Any) -> bool:
    """True if a history entry is a compaction checkpoint or previous summary."""
    if not isinstance(msg, dict):
        return False
    content = msg.get("content", "")
    if isinstance(content, str):
        return any(marker in content for marker in HISTORY_CHECKPOINT_MARKERS)
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                text = str(part.get("text", ""))
                if any(marker in text for marker in HISTORY_CHECKPOINT_MARKERS):
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
