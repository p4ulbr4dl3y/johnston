"""Prompt-toolkit session with Claude Code rounded boxed input layout."""
from __future__ import annotations

from functools import partial
from typing import List

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style

from johnston_cli.repl.session import ReplSession

BOX_STYLE = Style.from_dict({
    "border": "#0087d7",
    "prompt": "#00ffff bold",
    "model": "bg:#333333 #ffffff bold",
    "stats": "#888888",
    "help": "#666666",
    "completion-menu": "bg:#222222 #cccccc",
    "completion-menu.completion.current": "bg:#444444 #00ffff bold",
})


class ReplInput:
    """Manages interactive command prompt with rounded Claude Code box."""

    def __init__(self, session: ReplSession, command_names: List[str]) -> None:
        self.session = session
        self.completer = WordCompleter(command_names, ignore_case=True, sentence=True)
        self.history = InMemoryHistory()

    def _create_app(self) -> Application[str]:
        fill = partial(Window, style="class:border")
        buf = Buffer(
            completer=self.completer,
            history=self.history,
            multiline=False,
            complete_while_typing=False,
        )
        kb = KeyBindings()

        @kb.add("enter")
        def _on_enter(event):
            event.app.exit(result=buf.text)

        @kb.add("c-c")
        def _on_interrupt(event):
            buf.text = ""
            event.app.exit(result="")

        @kb.add("c-d")
        def _on_eof(event):
            event.app.exit(exception=EOFError)

        top_border = VSplit([
            fill(width=1, height=1, char="╭"),
            fill(char="─", height=1),
            fill(width=1, height=1, char="╮"),
        ], height=1)

        mid_row = VSplit([
            fill(width=1, char="│"),
            Window(FormattedTextControl([("class:prompt", " ❯ ")]), width=3, dont_extend_width=True),
            Window(BufferControl(buffer=buf)),
            fill(width=1, char="│"),
        ], height=1)

        def get_model():
            return [("class:model", f" {self.session.model_name} "), ("", " ")]

        def get_stats():
            cost_str = f"${self.session.total_cost_usd:.3f}" if self.session.total_cost_usd > 0 else "$0.00"
            return [("class:stats", f"{self.session.total_tokens:,} tokens ({cost_str}) "), ("", " ")]

        def get_help():
            return [("class:help", " ? /help  / commands ")]

        bot_border = VSplit([
            fill(width=1, height=1, char="╰"),
            fill(width=1, height=1, char="─"),
            Window(FormattedTextControl(get_model), dont_extend_width=True, height=1),
            Window(FormattedTextControl(get_stats), dont_extend_width=True, height=1),
            fill(char="─", height=1),
            Window(FormattedTextControl(get_help), dont_extend_width=True, height=1),
            fill(width=2, height=1, char="─"),
            fill(width=1, height=1, char="╯"),
        ], height=1)

        root = FloatContainer(
            content=HSplit([top_border, mid_row, bot_border]),
            floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=6))],
        )

        return Application(
            layout=Layout(root),
            key_bindings=kb,
            style=BOX_STYLE,
            full_screen=False,
            erase_when_done=True,
        )

    async def prompt_async(self) -> str:
        """Prompt user inside the rounded box."""
        app = self._create_app()
        return await app.run_async()
