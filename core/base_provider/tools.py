from typing import Any, Dict

from tools.registry import ALIAS_MAP


class ToolMixin:
    """Mixin providing tool-name canonicalization and runtime tool-policy checks for BaseAgent."""

    def _canonical_tool_name(self, tool_name: str) -> str:
        clean_name = (tool_name or "").strip()
        return ALIAS_MAP.get(clean_name.lower(), clean_name)

    def _tool_policy_error(self, tool_name: str, args: Dict[str, Any], mode_def: Any) -> str | None:
        from core.mode_manager import mode_tool_error

        clean_name = self._canonical_tool_name(tool_name).lower()
        return mode_tool_error(mode_def, clean_name)
