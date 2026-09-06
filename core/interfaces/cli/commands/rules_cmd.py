"""CLI rules command."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def run_rules(args: Any = None) -> int:
    """Print active project instructions and rules summary to stdout."""
    from core.application.generation.prompt_builder import INSTRUCTION_FILES
    from core.application.rules.rules import RulesManager

    print("Active Rules & Project Instructions:")
    cwd = Path.cwd()

    items = []
    for name in INSTRUCTION_FILES:
        filepath = cwd / name
        if filepath.is_file():
            try:
                size = filepath.stat().st_size
                items.append(("file", name, filepath, size))
            except Exception:
                pass

    rules = RulesManager.get_instance().load_rules()
    for r in rules:
        items.append(("rule", r.name, r.source))

    if not items:
        print("  No rules or project instruction files found (AGENTS.md, CLAUDE.md, .cursorrules, .johnston/rules/).")
        return 0

    for idx, item in enumerate(items):
        if item[0] == "file":
            _, name, filepath, size = item
            print(f"  * {name} [project instruction]")
            print(f"    Path: {filepath} ({size} bytes)")
        else:
            _, r_name, r_source = item
            scope = f"[{r_source}]"
            print(f"  * {r_name} [rule] {scope}")
        if idx < len(items) - 1:
            print()
    return 0


def print_rules() -> None:
    """Backward-compatible helper for legacy callers."""
    run_rules()
