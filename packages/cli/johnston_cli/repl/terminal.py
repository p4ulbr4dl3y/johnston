"""Terminal styling and output formatting utilities for Johnston CLI REPL."""
from __future__ import annotations

import shutil
import sys


def get_term_width() -> int:
    """Get current terminal width with reasonable fallback."""
    return max(40, shutil.get_terminal_size((80, 24)).columns)


def print_banner(version: str, model_name: str, branch: str | None) -> None:
    """Print clean startup header banner."""
    dim = "\033[90m"
    bold = "\033[1m"
    reset = "\033[0m"
    cyan = "\033[36m"

    branch_part = f" · branch: {branch}" if branch else ""
    header = f"{bold}{cyan}Johnston{reset} (v{version}) · {model_name}{branch_part}"
    hint = f"{dim}Type /help for commands, Ctrl+C to cancel, Ctrl+D to exit.{reset}"

    sys.stdout.write(f"\n{header}\n{hint}\n\n")
    sys.stdout.flush()


def print_top_separator() -> None:
    """Print top input border line."""
    dim = "\033[90m"
    reset = "\033[0m"
    width = get_term_width()
    sys.stdout.write(f"{dim}{'─' * width}{reset}\n")
    sys.stdout.flush()


def format_turn_footer(model_name: str, total_tokens: int, duration_s: float) -> str:
    """Format single-line turn summary footer."""
    width = get_term_width()
    dim = "\033[90m"
    reset = "\033[0m"

    tok_str = f"{total_tokens:,} tokens" if total_tokens else "0 tokens"
    info = f" {model_name} · {tok_str} · {duration_s:.1f}s "
    left = "───"
    needed = width - len(left) - len(info)
    right = "─" * max(3, needed)
    return f"\n{dim}{left}{info}{right}{reset}\n"
