from typing import Any


class ToolMixin:
    """Mixin providing tool-name canonicalization and runtime tool-policy checks for BaseAgent."""

    def _canonical_tool_name(self, tool_name: str) -> str:
        from tools.registry import normalize_tool_name

        return normalize_tool_name(tool_name or "")

    def _tool_policy_error(self, tool_name: str, mode_def: Any) -> str | None:
        from core.role_registry import role_tool_error

        clean_name = self._canonical_tool_name(tool_name).lower()
        return role_tool_error(mode_def, clean_name)
