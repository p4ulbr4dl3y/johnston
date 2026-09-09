"""Rich-based renderer and Claude Code status panels."""
from __future__ import annotations

from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from johnston_cli.repl.engine.events import ThinkingDoneEvent, ToolCallResultEvent
from johnston_cli.repl.session import ReplSession

EXPANDABLE_TOOLS = frozenset({"edit", "create", "shell", "search", "update_plan"})

COLOR_STATUS_RUNNING = "#d4a259"
COLOR_STATUS_SUCCESS = "#5ea876"
COLOR_STATUS_ERROR = "#d15858"
THEME_MUTED = "#71717a"
THEME_SECONDARY = "#a1a1aa"


def is_tool_expandable(tool_name: str) -> bool:
    """Check if a tool's results can be expanded/collapsed."""
    return (tool_name or "").strip().lower() in EXPANDABLE_TOOLS


def render_thinking(
    event: ThinkingDoneEvent,
    expanded: bool = False,
    show_hint: bool = True,
) -> Text:
    """Render thinking status matching Claude Code format: • Thought for Xs · Y tokens."""
    text = Text()
    text.append("• ", style=THEME_MUTED)
    text.append(f"Thought for {event.duration_s:.1f}s · {event.token_count} tokens", style=THEME_MUTED)

    has_content = bool(event.content and event.content.strip())
    if has_content and show_hint:
        hint = " (ctrl+o to collapse)" if expanded else " (ctrl+o to expand)"
        text.append(hint, style=THEME_MUTED)

    if has_content and expanded:
        for line in event.content.strip().splitlines():
            text.append("\n│ ", style="#3f3f46")
            text.append(line, style="dim italic")

    return text


def render_tool_call(
    event: ToolCallResultEvent,
    expanded: bool = False,
    show_hint: bool = True,
) -> Text:
    """Render tool call matching Johnston TUI Monochrome Slate status format: ● ToolName(target)."""
    text = Text()
    expandable = is_tool_expandable(event.tool_name)

    # Status marker & Tool Name (Johnston TUI Monochrome Slate: green = success, red = error)
    if event.is_error or (event.exit_code is not None and event.exit_code != 0):
        marker_glyph = "✖ "
        color = COLOR_STATUS_ERROR
    else:
        marker_glyph = "● "
        color = COLOR_STATUS_SUCCESS

    text.append(marker_glyph, style=f"bold {color}")
    text.append(event.tool_name, style=f"bold {color}")

    # Target / Arguments in secondary neutral gray #a1a1aa
    target_str = event.target or ""
    text.append(f"({target_str})", style=THEME_SECONDARY)

    # Expansion hint (only shown on the active/last expandable widget)
    if expandable and show_hint:
        hint = " (ctrl+o to collapse)" if expanded else " (ctrl+o to expand)"
        text.append(hint, style=THEME_MUTED)

    # Expanded details body
    if expandable and expanded:
        if event.diff:
            diff_lines = event.diff.strip().splitlines()
            for line in diff_lines:
                text.append("\n│ ", style="#3f3f46")
                if line.startswith("+"):
                    text.append(line, style=COLOR_STATUS_SUCCESS)
                elif line.startswith("-"):
                    text.append(line, style=COLOR_STATUS_ERROR)
                elif line.startswith("@@"):
                    text.append(line, style="#61afef")
                else:
                    text.append(line, style="dim")
        elif (event.tool_name or "").lower() == "shell":
            if event.target:
                text.append("\n│ ", style="#3f3f46")
                text.append(f"$ {event.target}", style="bold white")
            if event.summary:
                for line in event.summary.strip().splitlines():
                    text.append("\n│ ", style="#3f3f46")
                    text.append(line, style="dim")
        elif event.summary:
            for line in event.summary.strip().splitlines():
                text.append("\n│ ", style="#3f3f46")
                text.append(line, style="dim")

    return text


class ReplRenderer:
    """Renders events, tool cards, and live status box."""

    def __init__(self, console: Optional[Console] = None) -> None:
        self.console = console or Console(highlight=False)

    def render_welcome(self, session: ReplSession, is_mock: bool = True) -> None:
        """Render welcome banner upon starting REPL."""
        self.console.print()
        title = Text()
        title.append("● ", style="bold red")
        title.append("Johnston REPL ", style="bold white")
        title.append("v0.1.0 ", style="dim")
        if is_mock:
            title.append("(synthetic / mock)", style="bold yellow")
        else:
            title.append("(inline)", style="dim italic")

        self.console.print(title)
        self.console.print(
            f"[dim]Project: {session.working_dir} · Model: {session.model_name} · Role: {session.role}[/dim]"
        )
        self.console.print("[dim]Type /help for slash commands, Ctrl+C to abort turn, Ctrl+D to exit.[/dim]")
        self.console.print()

    def render_user_prompt(self, prompt: str) -> None:
        """Render user input line as a permanent message in terminal scrollback."""
        line = Text()
        line.append("❯ ", style="bold cyan")
        line.append(prompt, style="bold white")
        self.console.print(line)
        self.console.print()

    def make_status_box(self, status_text: str, session: ReplSession) -> Panel:
        """Create Claude Code status box shown at bottom during turn execution."""
        cost_str = f"${session.total_cost_usd:.3f}" if session.total_cost_usd > 0 else "$0.00"
        footer = Text()
        footer.append(f" {session.model_name} ", style="bg:#333333 #ffffff bold")
        footer.append(f" {session.total_tokens:,} tokens ({cost_str})", style="dim")
        footer.append(" " * 16)
        footer.append("Ctrl+C to abort", style="dim")

        return Panel(
            Text(f" {status_text}", style="cyan"),
            subtitle=footer,
            subtitle_align="left",
            box=box.ROUNDED,
            border_style="#0087d7",
            padding=(0, 1),
        )

    def render_tool_call(self, event: ToolCallResultEvent, expanded: bool = False) -> Text:
        """Render tool call matching Johnston TUI signature format."""
        return render_tool_call(event, expanded=expanded)

    def make_tool_panel(self, event: ToolCallResultEvent) -> Text:
        """Backward compatible tool rendering returning collapsed tool call line."""
        return self.render_tool_call(event, expanded=False)
