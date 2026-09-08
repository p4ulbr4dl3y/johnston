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
    hint = f"{dim}Команды: /help, выход: Ctrl+D или exit.{reset}"

    sys.stdout.write(f"\n{header}\n{hint}\n\n")
    sys.stdout.flush()


def print_top_separator() -> None:
    """Print top input border line."""
    dim = "\033[90m"
    reset = "\033[0m"
    width = max(20, get_term_width() - 1)
    sys.stdout.write(f"{dim}{'─' * width}{reset}\n")
    sys.stdout.flush()


def format_turn_footer(model_name: str, total_tokens: int, duration_s: float) -> str:
    """Format single-line turn summary footer."""
    width = max(20, get_term_width() - 1)
    dim = "\033[90m"
    reset = "\033[0m"

    tok_str = f"{total_tokens:,} tokens" if total_tokens else "0 tokens"
    info = f" {model_name} · {tok_str} · {duration_s:.1f}s "
    left = "───"
    needed = width - len(left) - len(info)
    right = "─" * max(3, needed)
    return f"\n{dim}{left}{info}{right}{reset}\n"


def pad_to_bottom() -> None:
    """Pad terminal with blank lines on startup so input is pinned to bottom."""
    lines = shutil.get_terminal_size((80, 24)).lines
    pad = max(0, lines - 8)
    if pad > 0:
        sys.stdout.write("\n" * pad)
        sys.stdout.flush()


def format_input_hint(model_name: str, branch: str, total_tokens: int) -> str:
    """Format the inline hint and status line directly below input."""
    width = max(20, get_term_width() - 1)
    dim = "\033[90m"
    bold = "\033[1m"
    cyan = "\033[36m"
    reset = "\033[0m"

    tok_str = f"{total_tokens:,} tokens" if total_tokens else "0 tokens"
    left_plain = f"  {model_name} | {branch} | {tok_str}"
    right_plain = "[Enter: send, Esc+Enter: newline]"
    spaces = " " * max(2, width - len(left_plain) - len(right_plain))

    left_styled = f"  {bold}{cyan}{model_name}{reset}{dim} | {branch} | {tok_str}{reset}"
    right_styled = f"{dim}{right_plain}{reset}"
    return f"{left_styled}{spaces}{right_styled}\n"
