"""Interactive prompt_toolkit session setup for Johnston CLI REPL."""
from __future__ import annotations

import os
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style


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
    """Create a configured prompt_toolkit PromptSession with keybindings and status bar."""
    kb = KeyBindings()

    @kb.add("enter")
    def _handle_enter(event):
        """Submit text on single Enter."""
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _handle_newline(event):
        """Insert newline on Esc+Enter."""
        event.current_buffer.insert_text("\n")

    def _bottom_toolbar() -> HTML:
        model_name, tokens = get_status_info()
        branch = get_current_git_branch()
        tok_str = f"{tokens:,} tokens" if tokens else "0 tokens"
        return HTML(
            f" <b>{model_name}</b> | {branch} | {tok_str} "
            f"<style color='#888888'>[Enter: send, Esc+Enter: newline, /help: commands]</style>"
        )

    style = Style.from_dict(
        {
            "prompt": "#00d7ff bold",
            "bottom-toolbar": "bg:#222222 #cccccc",
        }
    )

    return PromptSession[str](
        key_bindings=kb,
        bottom_toolbar=_bottom_toolbar,
        style=style,
        multiline=True,
    )
