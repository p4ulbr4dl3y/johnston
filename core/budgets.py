import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetLimits:
    max_steps: int | None = None
    max_tool_calls: int | None = None
    max_wall_seconds: float | None = None
    max_writes: int | None = None


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
        self.writes = 0

    def before_step(self) -> BudgetDecision:
        if self.limits.max_steps is not None and self.steps >= self.limits.max_steps:
            return BudgetDecision.block(
                f"Reached maximum agent loop steps ({self.limits.max_steps})."
            )
        if self.limits.max_wall_seconds is not None and (time.monotonic() - self.started_at > self.limits.max_wall_seconds):
            return BudgetDecision.block(
                f"Reached maximum wall-clock budget ({self.limits.max_wall_seconds:g}s)."
            )
        self.steps += 1
        return BudgetDecision.allow()

    def before_tool_call(self, capabilities: set[str] | None = None) -> BudgetDecision:
        if self.limits.max_tool_calls is not None and self.tool_calls >= self.limits.max_tool_calls:
            return BudgetDecision.block(
                f"Reached maximum tool-call budget ({self.limits.max_tool_calls})."
            )
        if self.limits.max_wall_seconds is not None and (time.monotonic() - self.started_at > self.limits.max_wall_seconds):
            return BudgetDecision.block(
                f"Reached maximum wall-clock budget ({self.limits.max_wall_seconds:g}s)."
            )
        capabilities = capabilities or set()
        if self.limits.max_writes is not None and "fs.write" in capabilities and self.writes >= self.limits.max_writes:
            return BudgetDecision.block(
                f"Reached maximum write budget ({self.limits.max_writes})."
            )
        self.tool_calls += 1
        if "fs.write" in capabilities:
            self.writes += 1
        return BudgetDecision.allow()

    def summarize(self) -> dict[str, int | float | None]:
        return {
            "steps": self.steps,
            "max_steps": self.limits.max_steps,
            "tool_calls": self.tool_calls,
            "max_tool_calls": self.limits.max_tool_calls,
            "writes": self.writes,
            "max_writes": self.limits.max_writes,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 3),
            "max_wall_seconds": self.limits.max_wall_seconds,
        }
