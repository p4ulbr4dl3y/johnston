"""Interactive prompt_toolkit session setup for Johnston CLI REPL."""
from __future__ import annotations

import os
from typing import Any, Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
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


class InlinePromptSession(PromptSession[str]):
    """PromptSession that embeds separator and status bar inline directly below the input buffer."""

    def __init__(
        self,
        get_status_info: Callable[[], tuple[str, int]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._get_status_info = get_status_info
        super().__init__(*args, **kwargs)

    def _create_layout(self):
        layout = super()._create_layout()
        try:
            main_hsplit = layout.container.children[0].content

            def _get_bottom_hint_fragments() -> StyleAndTextTuples:
                width = get_term_width()
                sep = "─" * width
                model_name, tokens = self._get_status_info()
                branch = get_current_git_branch()
                tok_str = f"{tokens:,} tokens" if tokens else "0 tokens"
                left = f"  {model_name} | {branch} | {tok_str}"
                right = "[Enter: send, Esc+Enter: newline]"
                spaces = " " * max(2, width - len(left) - len(right) - 2)

                return [
                    ("class:dim", f"{sep}\n"),
                    ("class:model", f"  {model_name}"),
                    ("class:dim", " | "),
                    ("class:branch", branch),
                    ("class:dim", " | "),
                    ("class:tokens", tok_str),
                    ("", spaces),
                    ("class:dim", f"{right}\n"),
                ]

            hint_window = Window(
                FormattedTextControl(_get_bottom_hint_fragments),
                dont_extend_height=True,
            )
            main_hsplit.children.append(hint_window)
        except Exception:
            pass
        return layout


def create_repl_prompt_session(
    get_status_info: Callable[[], tuple[str, int]],
) -> PromptSession[str]:
    """Create a configured prompt_toolkit PromptSession with keybindings and inline status."""
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
            "dim": "#666666",
            "model": "#00d7ff bold",
            "branch": "#888888",
            "tokens": "#aaaaaa",
        }
    )

    return InlinePromptSession(
        get_status_info=get_status_info,
        key_bindings=kb,
        style=style,
        multiline=True,
    )
