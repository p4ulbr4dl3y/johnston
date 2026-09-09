"""Slash commands handler for REPL."""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Tuple

from rich.console import Console
from rich.table import Table

from johnston_cli.repl.session import ReplSession


class CommandHandler:
    """Registry and dispatcher for REPL slash commands."""

    def __init__(
        self,
        console: Optional[Console] = None,
        output_func: Optional[Callable[[Any], None]] = None,
        clear_func: Optional[Callable[[], None]] = None,
    ) -> None:
        self.console = console or Console(highlight=False)
        self.output_func = output_func or self.console.print
        self.clear_func = clear_func
        self._commands: Dict[str, Tuple[str, Callable[[ReplSession, str], Optional[bool]]]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._commands["/help"] = ("Show available commands", self._cmd_help)
        self._commands["/clear"] = ("Clear the terminal screen", self._cmd_clear)
        self._commands["/tokens"] = ("Show token usage and estimated cost", self._cmd_tokens)
        self._commands["/model"] = ("Show or change active model", self._cmd_model)
        self._commands["/exit"] = ("Exit REPL", self._cmd_exit)
        self._commands["/quit"] = ("Exit REPL", self._cmd_exit)

    @property
    def command_names(self) -> list[str]:
        return list(self._commands.keys())

    def is_command(self, text: str) -> bool:
        return text.strip().startswith("/")

    def handle(self, text: str, session: ReplSession) -> Optional[bool]:
        """Execute command. Returns True if REPL should exit."""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd not in self._commands:
            self.output_func(f"[bold red]Unknown command:[/bold red] {cmd}. Type [cyan]/help[/cyan] for available commands.\n")
            return None

        _, handler = self._commands[cmd]
        return handler(session, arg)

    def _cmd_help(self, session: ReplSession, arg: str) -> None:
        table = Table(box=None, padding=(0, 2), show_header=False)
        table.add_column("Command", style="bold cyan")
        table.add_column("Description", style="dim")
        for name, (desc, _) in sorted(self._commands.items()):
            table.add_row(name, desc)
        self.output_func(table)

    def _cmd_clear(self, session: ReplSession, arg: str) -> None:
        if self.clear_func:
            self.clear_func()
        else:
            os.system("cls" if os.name == "nt" else "clear")

    def _cmd_tokens(self, session: ReplSession, arg: str) -> None:
        self.output_func(
            f"[dim]Total session tokens: [bold white]{session.total_tokens}[/bold white] · "
            f"Est. cost: [bold green]${session.total_cost_usd:.4f}[/bold green][/dim]\n"
        )

    def _cmd_model(self, session: ReplSession, arg: str) -> None:
        if arg.strip():
            session.model_name = arg.strip()
            self.output_func(f"[dim]Switched model to [bold white]{session.model_name}[/bold white][/dim]\n")
        else:
            self.output_func(f"[dim]Active model: [bold white]{session.model_name}[/bold white][/dim]\n")

    def _cmd_exit(self, session: ReplSession, arg: str) -> bool:
        return True
