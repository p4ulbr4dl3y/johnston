"""Thin helpers for tool display/normalization used by UI widgets.

Keeps ``widgets/chat_toolcall.py`` from importing ``tools.registry`` directly
on critical paths or from performing side-effect normalization during ``__init__``.

Pure presentation helpers (e.g. ``read_file_content``) live in
:mod:`widgets.utils.file_reader`.
"""

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
