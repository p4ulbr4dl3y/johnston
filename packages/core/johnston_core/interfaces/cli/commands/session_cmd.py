"""CLI commands for managing, pruning, and exporting sessions."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Optional

from johnston_core.domain.entities.session import AgentSession
from johnston_core.domain.policies.messages import is_ui_visible_user_message
from johnston_core.infrastructure.storage.session_serialization import to_dict as _session_to_dict
from johnston_core.infrastructure.storage.session_store import SessionStore
from johnston_core.interfaces.cli.formatter import format_table

__all__ = [
    "export_session",
    "list_sessions",
    "prune_sessions",
    "rm_session",
    "run_session",
]


def list_sessions(
    limit: Optional[int] = 20,
    store: Optional[SessionStore] = None,
    as_json: bool = False,
    show_all: bool = False,
) -> int:
    """Format and print table or JSON with saved sessions."""
    if store is None:
        store = SessionStore.get_instance()

    sessions = store.list_main_sessions()
    if not sessions:
        disk_sessions = store.list("main")
        if disk_sessions:
            sessions = [s.to_summary_dict() for s in disk_sessions]
            sessions.sort(
                key=lambda s: (float(s.get("updated_at") or 0.0), float(s.get("created_at") or 0.0)),
                reverse=True,
            )

    effective_limit = None if show_all else limit
    if effective_limit is not None and effective_limit > 0:
        sessions = sessions[:effective_limit]

    if as_json:
        data = [
            {
                "id": str(s.get("id") or ""),
                "title": str(s.get("title") or "Untitled"),
                "message_count": s.get("message_count") if s.get("message_count") is not None else s.get("turn_count", 0),
                "updated_at": s.get("updated_at") or s.get("created_at"),
            }
            for s in sessions
        ]
        print(json.dumps(data, indent=2))
        return 0

    if not sessions:
        print("No sessions found.")
        return 0

    headers = ["Session ID", "Title", "Messages count", "Last Updated"]
    rows: list[list[str]] = []

    for s in sessions:
        sid = str(s.get("id") or "")
        raw_title = str(s.get("title") or "Untitled")
        title = raw_title if len(raw_title) <= 60 else raw_title[:57] + "..."
        msg_count = str(s.get("message_count") if s.get("message_count") is not None else s.get("turn_count", 0))
        ts = s.get("updated_at") or s.get("created_at")
        if ts:
            try:
                updated_str = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                updated_str = str(ts)
        else:
            updated_str = "-"

        rows.append([sid, title, msg_count, updated_str])

    print(format_table(headers, rows))
    return 0


def rm_session(session_id: str, store: Optional[SessionStore] = None) -> int:
    """Delete a session by ID or title."""
    if not session_id or not session_id.strip():
        print("Error: Session ID is required.", file=sys.stderr)
        return 1

    if store is None:
        store = SessionStore.get_instance()

    sess = store.get(session_id)
    if sess is None:
        sess = store.find_session_by_title_or_id(session_id)

    if sess is None:
        print(f"Error: Session '{session_id}' not found.", file=sys.stderr)
        return 1

    target_id = sess.id
    store.delete(target_id)
    print(f"Session '{target_id}' deleted.")
    return 0


def prune_sessions(days: int = 14, store: Optional[SessionStore] = None) -> int:
    """Prune sessions older than N days."""
    if days < 0:
        print("Error: Days must be non-negative.", file=sys.stderr)
        return 1

    if store is None:
        store = SessionStore.get_instance()

    cutoff_ts = time.time() - (days * 86400)
    sessions = store.list("main")
    deleted_count = 0

    for sess in sessions:
        ts = sess.updated_at or sess.created_at or 0.0
        if ts < cutoff_ts:
            store.delete(sess.id)
            deleted_count += 1

    print(f"Pruned {deleted_count} session(s) older than {days} days.")
    return 0


def _format_markdown(sess: AgentSession) -> str:
    created_str = (
        datetime.fromtimestamp(float(sess.created_at)).strftime("%Y-%m-%d %H:%M:%S")
        if sess.created_at
        else "-"
    )
    updated_str = (
        datetime.fromtimestamp(float(sess.updated_at)).strftime("%Y-%m-%d %H:%M:%S")
        if sess.updated_at
        else "-"
    )

    lines: list[str] = [
        f"# Session: {sess.title}",
        "",
        f"- **Session ID:** {sess.id}",
        f"- **Role:** {sess.role}",
        f"- **Status:** {sess.status}",
        f"- **Created:** {created_str}",
        f"- **Updated:** {updated_str}",
        "",
        "---",
        "",
    ]

    if sess.messages:
        for msg in sess.messages:
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "user":
                if not is_ui_visible_user_message(msg):
                    continue
                text = msg.get("text", "")
                lines.append(f"### User\n\n{text}\n")
            elif mtype == "bot":
                text = msg.get("text", "")
                lines.append(f"### Assistant\n\n{text}\n")
            elif mtype == "thinking":
                text = msg.get("text", "")
                if text:
                    lines.append(f"> *Thinking: {text}*\n")
            elif mtype == "tool":
                tool_name = msg.get("tool_type") or msg.get("name") or "tool"
                args = msg.get("args")
                result = msg.get("result_text") or msg.get("result")
                lines.append(f"**Tool Call:** `{tool_name}`\n")
                if args:
                    lines.append(f"```json\n{json.dumps(args, indent=2, ensure_ascii=False, default=str)}\n```\n")
                if result:
                    lines.append(f"```\n{result}\n```\n")
            elif mtype == "event_divider":
                text = msg.get("text", "---")
                lines.append(f"*[{text}]*\n")
    elif sess.agent_history:
        for h in sess.agent_history:
            if not isinstance(h, dict):
                continue
            role = h.get("role", "message")
            content = h.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
            lines.append(f"### {role.capitalize()}\n\n{content}\n")

    return "\n".join(lines).strip() + "\n"


def export_session(
    session_id: str,
    format_: str = "md",
    output_file: Optional[str] = None,
    store: Optional[SessionStore] = None,
) -> int:
    """Export session as Markdown dialogue or JSON."""
    if not session_id or not session_id.strip():
        print("Error: Session ID is required.", file=sys.stderr)
        return 1

    if store is None:
        store = SessionStore.get_instance()

    sess = store.get(session_id)
    if sess is None:
        sess = store.find_session_by_title_or_id(session_id)

    if sess is None:
        print(f"Error: Session '{session_id}' not found.", file=sys.stderr)
        return 1

    if format_ == "json":
        data = _session_to_dict(sess)
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        content = _format_markdown(sess)

    if output_file:
        try:
            out_path = os.path.abspath(output_file)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Session '{sess.id}' exported to {output_file}.")
        except OSError as err:
            print(f"Error writing to '{output_file}': {err}", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(content)

    return 0


def run_session(args: Any = None, store: Optional[SessionStore] = None) -> int:
    """Execute session subcommand based on parsed arguments."""
    action = getattr(args, "session_action", None) if args is not None else None

    if action is None or action == "list":
        show_all = getattr(args, "all", False) is True
        raw_limit = getattr(args, "limit", None)
        limit = None if show_all else (20 if raw_limit is None else raw_limit)
        as_json = getattr(args, "json", False) is True
        if as_json or show_all:
            return list_sessions(limit=limit, store=store, as_json=as_json, show_all=show_all)
        return list_sessions(limit=limit, store=store)
    if action == "rm":
        session_id = getattr(args, "session_id", "")
        return rm_session(session_id, store=store)
    if action == "prune":
        days = getattr(args, "days", 14)
        return prune_sessions(days=days, store=store)
    if action == "export":
        session_id = getattr(args, "session_id", "")
        format_ = getattr(args, "format", "md")
        output = getattr(args, "output", None)
        return export_session(session_id, format_=format_, output_file=output, store=store)

    print(f"Error: Unknown session action '{action}'", file=sys.stderr)
    return 1
