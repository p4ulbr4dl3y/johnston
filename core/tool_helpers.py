"""Thin helpers for tool display/normalization used by UI widgets.

Keeps ``widgets/chat_toolcall.py`` from importing ``tools.registry`` directly
on critical paths or from performing side-effect normalization during ``__init__``.
"""

import os
from typing import Any, Dict


def normalize_tool_name(name: str) -> str:
    """Wrapper around ``tools.registry.normalize_tool_name``."""
    from tools.registry import normalize_tool_name as _registry_normalize

    return _registry_normalize(name)


def normalize_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Wrapper around ``tools.registry.normalize_tool_args``."""
    from tools.registry import normalize_tool_args as _registry_normalize_args

    return _registry_normalize_args(tool_name, args)


def is_system_tool(tool_type: str) -> bool:
    """Check whether *tool_type* is registered in the system tool registry."""
    if not isinstance(tool_type, str):
        return False
    from tools.registry import REGISTRY
    from tools.registry import normalize_tool_name as _normalize

    lower = tool_type.lower()
    canonical = _normalize(lower)
    if canonical in REGISTRY:
        return True
    return False


def get_all_tool_types() -> list[str]:
    """Return the sorted list of registered system tool type keys."""
    from tools.registry import REGISTRY

    return sorted(REGISTRY)


def read_file_content(file_path: str) -> str | None:
    """Read a file from disk for display purposes.

    Returns the file content (utf-8, errors='replace') or *None* when the
    path does not exist or read fails.  Widget callers should handle the
    *None* case gracefully (e.g. fall back to ``result_text``).
    """
    if not file_path:
        return None
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None
