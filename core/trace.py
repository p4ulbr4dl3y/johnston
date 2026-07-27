import json
import os
from collections import Counter
from typing import Any, Iterable


def iter_trace_events(path: str = ".johnston/trace.jsonl") -> Iterable[dict[str, Any]]:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield {"event": "trace_parse_error", "raw": line}
                continue
            if isinstance(event, dict):
                yield event


def summarize_trace(path: str = ".johnston/trace.jsonl") -> dict[str, Any]:
    events = list(iter_trace_events(path))
    decisions = Counter(
        event.get("decision", "unknown")
        for event in events
        if event.get("event") == "tool_decision"
    )
    tools = Counter(
        event.get("tool", "unknown")
        for event in events
        if event.get("event") in {"tool_decision", "tool_result"}
    )
    return {
        "events": len(events),
        "tool_decisions": dict(decisions),
        "tools": dict(tools),
    }


def format_trace_summary(path: str = ".johnston/trace.jsonl", *, limit: int = 8) -> str:
    events = list(iter_trace_events(path))
    summary = summarize_trace(path)
    recent = events[-limit:]
    lines = [
        f"Trace events: {summary['events']}",
        f"Tool decisions: {summary['tool_decisions']}",
        f"Tools: {summary['tools']}",
    ]
    if recent:
        lines.append("Recent events:")
        for event in recent:
            name = event.get("event", "unknown")
            tool = event.get("tool", "")
            decision = event.get("decision", "")
            reason = event.get("reason", "")
            detail = " ".join(str(x) for x in (tool, decision) if x)
            suffix = f" - {reason}" if reason else ""
            lines.append(f"- {name} {detail}{suffix}".rstrip())
    return "\n".join(lines)


def rollback_last_transaction(
    path: str = ".johnston/trace.jsonl",
    *,
    project_path: str | None = None,
) -> tuple[bool, str]:
    checkpoint = None
    for event in iter_trace_events(path):
        if event.get("event") == "transaction_checkpoint":
            checkpoint = event
    if not checkpoint:
        return False, "No transaction checkpoint found."

    try:
        from core.git_checkpoint import GitCheckpointManager

        ok = GitCheckpointManager.restore_checkpoint(
            str(checkpoint["session_id"]),
            int(checkpoint["message_index"]),
            project_path=project_path,
        )
    except Exception as exc:
        return False, f"Rollback failed: {exc}"
    if not ok:
        return False, "Rollback failed: checkpoint could not be restored."
    return True, f"Rolled back tool '{checkpoint.get('tool', 'unknown')}' to checkpoint {checkpoint.get('checkpoint_sha', '')[:8]}."
