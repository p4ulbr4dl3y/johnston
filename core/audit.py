import json
import os
import time
from typing import Any


def append_tool_decision(
    *,
    mode: str,
    tool: str,
    decision: str,
    reason: str,
    capabilities: set[str] | list[str] | tuple[str, ...] = (),
) -> None:
    try:
        os.makedirs(".johnston", exist_ok=True)
        record: dict[str, Any] = {
            "ts": time.time(),
            "mode": mode,
            "tool": tool,
            "decision": decision,
            "reason": reason,
            "capabilities": sorted(capabilities),
        }
        with open(os.path.join(".johnston", "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
