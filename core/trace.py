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
