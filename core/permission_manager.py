from typing import Any, Callable, Dict, FrozenSet, Optional, Tuple

from core.domain.defaults.config import DEFAULT_PERMISSIONS
from core.domain.policies.permission_policy import (
    _BUILTIN_TOOLS,
    VALID_ACTIONS,
    _merge_perms,
    normalize_action,
)
from core.infrastructure.platform.paths import CONFIG_FILE
from core.infrastructure.platform.platform_utils import atomic_write_json


class PermissionManager:
    """Manages tool execution permissions (allow, ask, deny) with config cascade."""

    VALID_ACTIONS = VALID_ACTIONS

    _instance: Optional["PermissionManager"] = None

    def __init__(
        self,
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
        builtin_tool_names: Optional[FrozenSet[str]] = None,
    ):
        self.session_overrides: Dict[str, str] = {}
        self.tool_name_normalizer = tool_name_normalizer
        self.builtin_tool_names = builtin_tool_names if builtin_tool_names is not None else _BUILTIN_TOOLS

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def normalize_action(action: str, default: str = "ask") -> str:
        """Normalizes an action to 'allow'/'ask'/'deny'. Invalid values fall back to default."""
        return normalize_action(action, default)

    def set_session_override(self, tool_name: str, action: str) -> None:
        """Sets a runtime session override for a tool (e.g. 'allow', 'deny'). Invalid actions are ignored."""
        normalized = normalize_action(action)
        if normalized in VALID_ACTIONS:
            canonical = self._normalize_name(tool_name or "")
            self.session_overrides[canonical] = normalized

    def _normalize_name(self, tool_name: str) -> str:
        """Canonicalizes a tool name via the injected normalizer, falling back
        to a plain lowercase strip when none is provided."""
        if self.tool_name_normalizer:
            try:
                return self.tool_name_normalizer(tool_name)
            except Exception:
                return (tool_name or "").strip().lower()
        return (tool_name or "").strip().lower()

    def clear_session_overrides(self) -> None:
        self.session_overrides.clear()

    def _load_json_config(self, filepath: str) -> Dict[str, Any]:
        from core.models_catalog import cached_json_read

        data = cached_json_read(filepath, {})
        return data if isinstance(data, dict) else {}

    def update_permission(self, target_type: str, target_name: str, action: str) -> None:
        """
        Updates a global tool permission setting to action.
        Raises ValueError on invalid target_type or action.
        Saves to the global config file (~/.johnston/config.json).
        """
        if target_type != "tool":
            raise ValueError(f"Invalid target_type: '{target_type}'")

        target_name = (target_name or "").strip().lower()
        target_name = self._normalize_name(target_name)

        # Validate the raw value BEFORE normalization: normalize_action() would
        # turn junk into the valid 'ask' default and mask the error.
        raw = (action or "").strip().lower()
        if raw not in self.VALID_ACTIONS:
            raise ValueError(f"Invalid action '{action}' for {target_type} '{target_name}'")
        action = raw

        file_path = CONFIG_FILE
        data = self._load_json_config(file_path)
        if "permissions" not in data or not isinstance(data["permissions"], dict):
            data["permissions"] = {}
        perms = data["permissions"]

        if "tools" not in perms or not isinstance(perms["tools"], dict):
            perms["tools"] = {}
        perms["tools"][target_name] = action

        atomic_write_json(file_path, data)

    def get_effective_permissions(self) -> Dict[str, Any]:
        """Merges global config on top of DEFAULT_PERMISSIONS."""
        # 1. Base defaults
        merged = {
            "default": DEFAULT_PERMISSIONS.get("default", "ask"),
            "tools": dict(DEFAULT_PERMISSIONS.get("tools", {})),
        }

        # 2. Global config (~/.johnston/config.json)
        global_cfg = self._load_json_config(CONFIG_FILE)
        global_perms = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
        _merge_perms(merged, global_perms)

        return merged

    def check_permission(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """
        Evaluates permission for executing a tool.

        Returns (action, reason) where action is 'allow', 'ask', or 'deny'.
        """
        raw_tool = (tool_name or "").strip().lower()
        canonical_name = self._normalize_name(raw_tool)
        # Fail-closed: an empty/absent tool name must never grant execution.
        if not canonical_name:
            return "deny", "No tool name given"

        effective_perms = self.get_effective_permissions()

        # 1. Check runtime session overrides
        if canonical_name in self.session_overrides:
            return self.session_overrides[canonical_name], f"Session override for '{canonical_name}'"

        # 2. Check tool-specific config
        tools_cfg = effective_perms.get("tools", {})
        if canonical_name in tools_cfg:
            return tools_cfg[canonical_name], f"Explicit tool permission for '{canonical_name}'"

        # 3. MCP tools (not in the builtin registry) default to 'allow' so that
        #    connected servers work out of the box; explicit config still applies.
        if canonical_name not in self.builtin_tool_names:
            # Fail-closed: a broken raw 'default' config must never silently allow.
            global_cfg = self._load_json_config(CONFIG_FILE)
            perms_cfg = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
            raw_default = perms_cfg.get("default")
            if raw_default is not None:
                norm_default = normalize_action(raw_default)
                if norm_default in VALID_ACTIONS:
                    return norm_default, f"MCP tool '{canonical_name}' applies configured default '{norm_default}'"
                return "deny", f"Invalid default configured; MCP tool '{canonical_name}' fails closed"
            return "allow", f"MCP tool default for '{canonical_name}'"

        # 4. Fallback to default
        default_action = effective_perms.get("default", "ask")
        # Fail-closed: any unexpected value becomes 'ask' (user confirmation), never silent 'allow'.
        return normalize_action(default_action), f"Default permission fallback for '{canonical_name}'"
