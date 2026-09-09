"""Inline REPL implementation for Johnston (`j`)."""
from __future__ import annotations

from typing import Any, Optional

from johnston_cli.repl.app import ReplApp


def start_repl(initial_prompt: Optional[str] = None, args: Any = None) -> int:
    """Launch interactive inline REPL."""
    model = getattr(args, "model", None) if args else None
    role = getattr(args, "role", None) if args else None
    app = ReplApp(model=model, role=role, initial_prompt=initial_prompt)
    return app.run()


__all__ = ["ReplApp", "start_repl"]
