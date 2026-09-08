"""Interactive prompt_toolkit session setup for Johnston CLI REPL."""
from __future__ import annotations

import os

from prompt_toolkit import PromptSession
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


def create_repl_prompt_session() -> PromptSession[str]:
    """Create a configured prompt_toolkit PromptSession with keybindings."""
    kb = KeyBindings()

    @kb.add("enter")
    def _handle_enter(event):
        """Submit text on single Enter."""
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _handle_newline(event):
        """Insert newline on Esc+Enter."""
        event.current_buffer.insert_text("\n")

    style = Style.from_dict(
        {
            "prompt": "#00d7ff bold",
        }
    )

    return PromptSession[str](
        key_bindings=kb,
        style=style,
        multiline=True,
    )
