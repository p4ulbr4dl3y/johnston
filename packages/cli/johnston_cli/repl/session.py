"""REPL session state tracker."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ReplSession:
    """State of active REPL session."""
    model_name: str = "claude-3-7-sonnet"
    role: str = "assistant"
    working_dir: str = field(default_factory=os.getcwd)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)

    def record_turn(self, prompt: str, response: str, tokens: int, cost: float) -> None:
        """Record turn metrics and history."""
        self.history.append({"role": "user", "content": prompt})
        self.history.append({"role": "assistant", "content": response})
        self.total_tokens += tokens
        self.total_cost_usd += cost
