"""Domain entity for AgentRole."""
from enum import Enum
from typing import Any, Callable, List, Optional

from johnston.core.domain.policies.provider import split_provider_model


class RoleScope(str, Enum):
    """The agent contexts a role applies to."""

    BOTH = "any"
    MAIN = "main"
    SUBAGENT = "subagent"


def normalize_role_scope(scope: Any) -> str:
    """Normalize a role scope value to its canonical short name."""
    if hasattr(scope, "value"):
        scope = scope.value
    clean = (scope or "").strip().lower()
    if clean in ("both", "all"):
        return "any"
    return clean or "any"


class AgentRole:
    """Unified definition for agent execution roles and modes."""

    def __init__(
        self,
        key: str,
        name: str = "",
        description: str = "",
        prompt: str = "",
        disallowed_tools: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        model: str = "",
        scope: str = "any",
        source: str = "builtin",
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
        read_only: bool = False,
    ):
        self.key = key.lower().strip()
        self.name = name or self.key.capitalize()
        self.description = description
        self.prompt = prompt or ""
        self.disallowed_tools = [t.strip() for t in (disallowed_tools or [])]
        self.allowed_tools = [t.strip() for t in (allowed_tools or [])]
        raw_model = (model or "").strip()
        if raw_model:
            if "/" not in raw_model:
                raise ValueError(
                    f"Invalid model format '{raw_model}' for role '{self.key}': must be 'provider/model'"
                )
            p, m = split_provider_model(raw_model)
            if not p or not m:
                raise ValueError(
                    f"Invalid model format '{raw_model}' for role '{self.key}': must be 'provider/model'"
                )
            self.provider = p
            self.model = m
        else:
            self.provider = ""
            self.model = ""
        self.scope = normalize_role_scope(scope)
        self.source = source
        self.tool_name_normalizer = tool_name_normalizer
        self.read_only = bool(read_only)


__all__ = ["AgentRole", "RoleScope", "normalize_role_scope"]
