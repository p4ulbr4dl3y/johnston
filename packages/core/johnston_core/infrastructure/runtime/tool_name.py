"""Tool-name canonicalization shared across core/, tools/ and widgets/.

A single source of truth for the ``strip + lowercase`` normalization that used
to be duplicated in several modules. None-safe (treats ``None`` as ``""``).
No other imports -> importable from any layer without cycles.
"""


def normalize_tool_name(name: str) -> str:
    """Normalize a tool name for case/whitespace-insensitive dispatch.

    Strip + lowercase only. No alias resolution. ``None`` -> ``""``.
    """
    if not name:
        return ""
    return name.strip().lower()
