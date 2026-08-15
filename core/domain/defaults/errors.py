"""Pure error-string helpers for the domain layer. No IO, no state."""

__all__ = ["format_tool_error"]


def format_tool_error(kind: str, detail: str = "", name: str = "") -> str:
    """Unified error prefix for tool/agent messages.

    Produces `ERR: <kind> '<name>': <detail>` (or `ERR: <kind>` when both name
    and detail are empty). Matches the existing de-facto `ERR:` convention.
    """
    base = f"ERR: {kind}"
    if name:
        base += f" '{name}'"
    if detail:
        base += f": {detail}"
    return base
