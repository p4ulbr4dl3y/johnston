from dataclasses import dataclass, field
from typing import Any

from core.budgets import BudgetLimits, BudgetState
from core.mode_manager import ModeManager


@dataclass(frozen=True)
class ToolAttempt:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    expect: str = "allow"
    approved: bool = False


@dataclass(frozen=True)
class HarnessScenario:
    name: str
    mode: str
    attempts: tuple[ToolAttempt, ...]
    budget_limits: BudgetLimits = field(default_factory=BudgetLimits)


@dataclass(frozen=True)
class HarnessEvalResult:
    scenario: str
    passed: bool
    failures: tuple[str, ...] = ()


def run_harness_scenario(scenario: HarnessScenario) -> HarnessEvalResult:
    mode_def = ModeManager.get_instance().get_mode(scenario.mode)
    budget = BudgetState(scenario.budget_limits)
    failures: list[str] = []

    disallowed = [t.lower() for t in (getattr(mode_def, "disallowed_tools", []) or [])]

    for idx, attempt in enumerate(scenario.attempts, start=1):
        budget_decision = budget.before_tool_call()
        if not budget_decision.allowed:
            actual = "block"
            reason = budget_decision.reason
        elif attempt.tool.lower() in disallowed:
            actual = "block"
            reason = f"Tool '{attempt.tool}' is disabled in {mode_def.name} mode."
        else:
            actual = "allow"
            reason = "Allowed"

        if actual != attempt.expect:
            failures.append(
                f"{scenario.name}:{idx} expected {attempt.expect} for {attempt.tool}, got {actual}: {reason}"
            )

    return HarnessEvalResult(scenario.name, not failures, tuple(failures))


def run_harness_scenarios(scenarios: list[HarnessScenario]) -> list[HarnessEvalResult]:
    return [run_harness_scenario(scenario) for scenario in scenarios]


def default_harness_scenarios() -> list[HarnessScenario]:
    return [
        HarnessScenario(
            name="explore-read-only",
            mode="explore",
            attempts=(
                ToolAttempt("read", {"path": "README.md"}, "allow"),
                ToolAttempt("shell", {"command": "rg policy core tests"}, "allow"),
                ToolAttempt("create", {"path": "x.txt", "content": "x"}, "block"),
            ),
        ),
        HarnessScenario(
            name="tool-budget",
            mode="action",
            attempts=(
                ToolAttempt("read", {"path": "README.md"}, "allow"),
                ToolAttempt("read", {"path": "README.md"}, "block"),
            ),
            budget_limits=BudgetLimits(max_tool_calls=1),
        ),
    ]
