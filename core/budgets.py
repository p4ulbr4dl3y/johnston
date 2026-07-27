import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetLimits:
    max_steps: int = 50
    max_tool_calls: int = 200
    max_wall_seconds: float = 30 * 60
    max_tool_result_chars: int = 120_000


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str = "Allowed"

    @classmethod
    def allow(cls) -> "BudgetDecision":
        return cls(True)

    @classmethod
    def block(cls, reason: str) -> "BudgetDecision":
        return cls(False, reason)


class BudgetState:
    def __init__(self, limits: BudgetLimits | None = None):
        self.limits = limits or BudgetLimits()
        self.started_at = time.monotonic()
        self.steps = 0
        self.tool_calls = 0

    def before_step(self) -> BudgetDecision:
        if self.steps >= self.limits.max_steps:
            return BudgetDecision.block(
                f"Reached maximum agent loop steps ({self.limits.max_steps})."
            )
        if time.monotonic() - self.started_at > self.limits.max_wall_seconds:
            return BudgetDecision.block(
                f"Reached maximum wall-clock budget ({self.limits.max_wall_seconds:g}s)."
            )
        self.steps += 1
        return BudgetDecision.allow()

    def before_tool_call(self) -> BudgetDecision:
        if self.tool_calls >= self.limits.max_tool_calls:
            return BudgetDecision.block(
                f"Reached maximum tool-call budget ({self.limits.max_tool_calls})."
            )
        if time.monotonic() - self.started_at > self.limits.max_wall_seconds:
            return BudgetDecision.block(
                f"Reached maximum wall-clock budget ({self.limits.max_wall_seconds:g}s)."
            )
        self.tool_calls += 1
        return BudgetDecision.allow()

    def summarize(self) -> dict[str, int | float]:
        return {
            "steps": self.steps,
            "max_steps": self.limits.max_steps,
            "tool_calls": self.tool_calls,
            "max_tool_calls": self.limits.max_tool_calls,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 3),
            "max_wall_seconds": self.limits.max_wall_seconds,
        }
