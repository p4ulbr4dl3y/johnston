"""Interruption and compaction divider helpers for AgentSession.

Unifies the finalization logic previously split between
``AgentSession.record_interruption`` / ``record_compaction`` and the module
functions ``record_session_interruption`` / ``record_session_compaction``:
agent sessions and duck-typed lookalikes both go through the same path.
"""
from typing import Any

from core.domain.entities.session import AgentSession, MessageType


def record_session_interruption(session: Any, divider_text: str = "Response Interrupted") -> None:
    """Unify cancellation/interruption finalization across main agent and subagents."""
    if not session:
        return
    if isinstance(session, AgentSession):
        _finalize_open_messages(session, divider_text)
        return
    if hasattr(session, "messages") and session.messages:
        for msg in reversed(session.messages):
            if isinstance(msg, dict):
                if msg.get("type") == MessageType.TOOL.value and "result_text" not in msg:
                    _safe_add_event(session, {
                        "type": MessageType.TOOL.value,
                        "result_text": "[interrupted | tool cancelled]",
                        "status": "cancelled",
                    })
                elif msg.get("type") == MessageType.THINKING.value and "duration" not in msg:
                    _safe_add_event(session, {
                        "type": MessageType.THINKING.value,
                        "duration": 0.0,
                    })
                else:
                    break
    _add_divider(session, divider_text)


def record_session_compaction(session: Any, title: str = "Session Compacted") -> None:
    """Unify compaction divider recording across session instances."""
    if not session:
        return
    if isinstance(session, AgentSession):
        _add_divider(session, title)
        return
    _add_divider(session, title)


def _finalize_open_messages(session: AgentSession, divider_text: str) -> None:
    """Finalize any in-flight tool or thinking events and append an interruption divider."""
    if session.messages:
        for msg in reversed(session.messages):
            if isinstance(msg, dict):
                if msg.get("type") == MessageType.TOOL.value and "result_text" not in msg:
                    session.add_event({
                        "type": MessageType.TOOL.value,
                        "result_text": "[interrupted | tool cancelled]",
                        "status": "cancelled",
                    })
                elif msg.get("type") == MessageType.THINKING.value and "duration" not in msg:
                    session.add_event({
                        "type": MessageType.THINKING.value,
                        "duration": 0.0,
                    })
                else:
                    break
    _add_divider(session, divider_text)


def _add_divider(session: Any, text: str) -> None:
    if hasattr(session, "add_event"):
        try:
            session.add_event({"type": MessageType.EVENT_DIVIDER.value, "text": text})
        except Exception:
            pass


def _safe_add_event(session: Any, event: dict) -> None:
    if hasattr(session, "add_event"):
        try:
            session.add_event(event)
        except Exception:
            pass
