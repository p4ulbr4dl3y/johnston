import json
import os
from dataclasses import dataclass, field
from typing import Any

from core.budgets import BudgetLimits

POLICY_CONFIG_PATH = os.path.join(".johnston", "policy.json")


@dataclass(frozen=True)
class PolicyConfig:
    capability_actions: dict[str, str] = field(default_factory=dict)
    tool_actions: dict[str, str] = field(default_factory=dict)
    budgets: BudgetLimits = field(default_factory=BudgetLimits)

    def action_for(self, *, tool: str, capabilities: set[str], default: str) -> str:
        tool_action = self.tool_actions.get(tool)
        if tool_action:
            return tool_action
        for capability in sorted(capabilities):
            action = self.capability_actions.get(capability)
            if action:
                return action
        return default


def _clean_action(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if value in {"allow", "ask", "block"}:
        return value
    return None


def _load_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_policy_config(path: str = POLICY_CONFIG_PATH) -> PolicyConfig:
    data = _load_json(path)
    raw_capabilities = data.get("capabilities", {})
    raw_tools = data.get("tools", {})
    raw_budgets = data.get("budgets", {})

    capability_actions: dict[str, str] = {}
    if isinstance(raw_capabilities, dict):
        for capability, rule in raw_capabilities.items():
            action = _clean_action(rule.get("action") if isinstance(rule, dict) else rule)
            if action:
                capability_actions[str(capability)] = action

    tool_actions: dict[str, str] = {}
    if isinstance(raw_tools, dict):
        for tool, rule in raw_tools.items():
            action = _clean_action(rule.get("action") if isinstance(rule, dict) else rule)
            if action:
                tool_actions[str(tool).lower()] = action

    budgets = BudgetLimits()
    if isinstance(raw_budgets, dict):
        budget_values = {}
        for name in (
            "max_steps",
            "max_tool_calls",
            "max_wall_seconds",
            "max_tool_result_chars",
            "max_writes",
            "max_changed_files",
            "max_diff_lines",
        ):
            value = raw_budgets.get(name)
            if isinstance(value, (int, float)) and value >= 0:
                budget_values[name] = value
        budgets = BudgetLimits(**{**budgets.__dict__, **budget_values})

    return PolicyConfig(
        capability_actions=capability_actions,
        tool_actions=tool_actions,
        budgets=budgets,
    )
