import json
import os
from dataclasses import dataclass, field
from typing import Any

from core.budgets import BudgetLimits

POLICY_CONFIG_PATH = os.path.join(".johnston", "policy.json")
ACTION_PRIORITY = {"allow": 0, "ask": 1, "block": 2}


@dataclass(frozen=True)
class PolicyConfig:
    capability_actions: dict[str, str] = field(default_factory=dict)
    tool_actions: dict[str, str] = field(default_factory=dict)
    budgets: BudgetLimits = field(default_factory=BudgetLimits)

    def action_for(self, *, tool: str, capabilities: set[str], default: str) -> str:
        actions = [default]
        tool_action = self.tool_actions.get(tool)
        if tool_action:
            actions.append(tool_action)
        actions.extend(
            action
            for capability in capabilities
            if (action := self.capability_actions.get(capability))
        )
        return max(actions, key=lambda action: ACTION_PRIORITY.get(action, 0))


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


def save_policy_config(config_data: dict[str, Any], path: str = POLICY_CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)


def set_policy_action(
    key_type: str, item_name: str, action: str, path: str = POLICY_CONFIG_PATH
) -> str:
    action = action.strip().lower()
    if action not in {"allow", "ask", "block"}:
        action = "allow"
    data = _load_json(path)
    section = "tools" if key_type == "tool" else "capabilities"
    if section not in data or not isinstance(data[section], dict):
        data[section] = {}
    data[section][item_name] = action
    save_policy_config(data, path)
    return action


def toggle_policy_action(
    key_type: str, item_name: str, path: str = POLICY_CONFIG_PATH
) -> str:
    data = _load_json(path)
    section = "tools" if key_type == "tool" else "capabilities"
    current_map = data.get(section, {}) if isinstance(data.get(section), dict) else {}
    current = current_map.get(item_name, "allow")
    if isinstance(current, dict):
        current = current.get("action", "allow")
    current = str(current).lower()
    next_action_map = {"allow": "ask", "ask": "block", "block": "allow"}
    new_action = next_action_map.get(current, "allow")
    return set_policy_action(key_type, item_name, new_action, path)


def set_budget_limit(
    limit_name: str, value: int | float | None, path: str = POLICY_CONFIG_PATH
) -> Any:
    data = _load_json(path)
    if "budgets" not in data or not isinstance(data["budgets"], dict):
        data["budgets"] = {}
    if value is None or (isinstance(value, (int, float)) and value < 0):
        data["budgets"].pop(limit_name, None)
    else:
        data["budgets"][limit_name] = value
    save_policy_config(data, path)
    return value


def cycle_budget_limit(limit_name: str, path: str = POLICY_CONFIG_PATH) -> Any:
    data = _load_json(path)
    raw_budgets = data.get("budgets", {}) if isinstance(data.get("budgets"), dict) else {}
    current = raw_budgets.get(limit_name)

    preset_map: dict[str, list[Any]] = {
        "max_steps": [None, 50, 100, 200],
        "max_tool_calls": [None, 100, 200, 500],
        "max_wall_seconds": [None, 900, 1800, 3600],
        "max_writes": [None, 20, 50, 100],
        "max_changed_files": [None, 50, 100, 200],
        "max_diff_lines": [None, 1000, 5000, 10000],
        "max_tool_result_chars": [None, 50000, 120000, 250000],
    }

    presets = preset_map.get(limit_name, [None, 50, 100])
    try:
        idx = presets.index(current)
        next_val = presets[(idx + 1) % len(presets)]
    except ValueError:
        next_val = presets[0]

    return set_budget_limit(limit_name, next_val, path)

