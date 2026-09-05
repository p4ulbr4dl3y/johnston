from typing import Any, Dict, List, Optional

from rich.markup import escape

from widgets.presentation.tool_display import extract_tool_display, format_compact_dict, truncate
from widgets.presentation.widgets.chat_markdown import to_snake_case
from widgets.presentation.widgets.footer_layout import get_theme_colors


def build_toolcall_header(
    canonical_tool: str,
    tool_type: Optional[str],
    args: Dict[str, Any],
    target: Any,
    status: str,
    status_color: str,
    system_tools: frozenset[str],
    display_names: Dict[str, str],
    is_mcp: bool,
    is_subagent: bool,
    background_task_id: Optional[str],
    is_expandable: bool,
    is_expanded: bool,
    show_hints: bool = True,
) -> str:
    """Builds rich markup string for toolcall header label."""
    marker = "○" if status == "generating" else "●"
    if canonical_tool in system_tools or canonical_tool in (
        "invoke_subagent",
        "manage_subagent",
        "manage_shell",
        "ask_user",
    ):
        display_name = display_names.get(canonical_tool, tool_type or "Tool")
        if canonical_tool == "update_plan":
            target_str = extract_tool_display(canonical_tool, args)
        else:
            extracted = extract_tool_display(canonical_tool, args) if args else ""
            target_str = extracted or (truncate(str(target), max_len=60) if target else "")
        base_header = f"[{status_color}]{marker} [bold]{display_name}[/bold][/{status_color}]({escape(str(target_str))})"
    else:
        compact = format_compact_dict(args)
        if status == "generating" and not compact:
            compact = truncate(str(target), max_len=60) if target else ""
        mcp_flag = (tool_type or "").startswith("mcp_") or is_mcp
        tool_name_display = to_snake_case(tool_type) if mcp_flag else (tool_type or "Tool")
        escaped_compact = escape(str(compact))
        base_header = f"[{status_color}]{marker} [bold]{tool_name_display}[/bold][/{status_color}]({escaped_compact})"

    hints: List[str] = []
    if show_hints and status == "running":
        if not is_subagent and canonical_tool == "shell" and not background_task_id:
            hints.append("ctrl+b to bg")
        if is_expandable:
            action = "to collapse" if is_expanded else "to expand"
            hints.append(f"ctrl+o {action}")

    if hints:
        _, _, t_muted, _ = get_theme_colors()
        hints_str = ", ".join(hints)
        return f"{base_header} [{t_muted}]({hints_str})[/]"
    return base_header
