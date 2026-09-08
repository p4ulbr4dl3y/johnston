"""Interactive prompt_toolkit session setup for Johnston CLI REPL."""
from __future__ import annotations

import os
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from johnston_cli.repl.terminal import get_term_width


def get_current_git_branch() -> str:
    """Best-effort git branch detection for active directory."""
    try:
        head_file = os.path.join(".git", "HEAD")
        if os.path.exists(head_file):
            with open(head_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content.startswith("ref: refs/heads/"):
                    return content[len("ref: refs/heads/") :]
    except Exception:
        pass
    return "main"


def create_repl_prompt_session(
    get_status_info: Callable[[], tuple[str, int]],
) -> PromptSession[str]:
    """Create a configured prompt_toolkit PromptSession with keybindings and bottom status."""
    kb = KeyBindings()

    @kb.add("enter")
    def _handle_enter(event):
        """Submit text on single Enter."""
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _handle_newline(event):
        """Insert newline on Esc+Enter."""
        event.current_buffer.insert_text("\n")

    def _bottom_toolbar() -> StyleAndTextTuples:
        width = max(20, get_term_width() - 1)
        sep = "─" * width
        model_name, tokens = get_status_info()
        branch = get_current_git_branch()
        tok_str = f"{tokens:,} tokens" if tokens else "0 tokens"
        left = f"  {model_name} | {branch} | {tok_str}"
        right = "[Enter: send, Esc+Enter: newline]"
        spaces = " " * max(2, width - len(left) - len(right))
        return [
            ("class:dim", f"{sep}\n"),
            ("class:model", f"  {model_name}"),
            ("class:dim", " | "),
            ("class:branch", branch),
            ("class:dim", " | "),
            ("class:tokens", tok_str),
            ("", spaces),
            ("class:dim", right),
        ]

    style = Style.from_dict(
        {
            "prompt": "#00d7ff bold",
            "bottom-toolbar": "noinherit #888888",
            "bottom-toolbar.text": "noinherit",
            "dim": "#666666",
            "model": "#00d7ff bold",
            "branch": "#888888",
            "tokens": "#aaaaaa",
        }
    )

    return PromptSession[str](
        key_bindings=kb,
        bottom_toolbar=_bottom_toolbar,
        style=style,
        multiline=True,
    )
