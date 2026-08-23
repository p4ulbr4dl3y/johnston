from typing import Any, Callable, Dict, FrozenSet, List, Optional

from core.domain.defaults.config import DEFAULT_PERMISSIONS
from core.domain.policies.permission_policy import (
    _BUILTIN_TOOLS,
    VALID_ACTIONS,
    PermissionAction,
    PermissionDecision,
    _merge_perms,
    evaluate_pattern_rules,
    normalize_action,
)
from core.infrastructure.platform.paths import CONFIG_FILE
from core.infrastructure.platform.platform_utils import atomic_write_json
from core.infrastructure.runtime.tool_name import normalize_tool_name


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
        self.session_pattern_overrides: Dict[str, List[Dict[str, str]]] = {}
        self.tool_name_normalizer = tool_name_normalizer
        self.builtin_tool_names = builtin_tool_names if builtin_tool_names is not None else _BUILTIN_TOOLS

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_session_override(self, tool_name: str, action: str) -> None:
        """Sets a runtime session override for a tool (e.g. 'allow', 'deny'). Invalid actions are ignored."""
        raw = (action or "").strip().lower()
        if raw not in self.VALID_ACTIONS:
            return  # silently ignore (consistent with docstring)
        canonical = self._normalize_name(tool_name or "")
        self.session_overrides[canonical] = raw

    def set_session_pattern_override(self, tool_name: str, pattern: str, action: str) -> None:
        """Sets a runtime session pattern override for a tool."""
        raw = (action or "").strip().lower()
        if raw not in self.VALID_ACTIONS:
            return  # silently ignore (consistent with docstring)
        pat = (pattern or "").strip()
        if not pat:
            return
        canonical = self._normalize_name(tool_name or "")
        if canonical not in self.session_pattern_overrides:
            self.session_pattern_overrides[canonical] = []
        # Prepend or replace existing rule for this exact pattern
        existing = [r for r in self.session_pattern_overrides[canonical] if r.get("pattern") != pat]
        self.session_pattern_overrides[canonical] = [{"pattern": pat, "action": raw}] + existing

    def _normalize_name(self, tool_name: str) -> str:
        """Canonicalizes a tool name via the injected normalizer, falling back
        to the shared normalize_tool_name when none is provided."""
        if self.tool_name_normalizer:
            try:
                return self.tool_name_normalizer(tool_name)
            except Exception:
                return normalize_tool_name(tool_name)
        return normalize_tool_name(tool_name)

    def clear_session_overrides(self) -> None:
        self.session_overrides.clear()
        self.session_pattern_overrides.clear()

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

    def update_pattern_permission(self, target_name: str, pattern: str, action: str) -> None:
        """
        Appends or updates a pattern permission in global config (~/.johnston/config.json).
        """
        target_name = self._normalize_name(target_name)
        raw_action = (action or "").strip().lower()
        if raw_action not in self.VALID_ACTIONS:
            raise ValueError(f"Invalid action '{action}' for pattern '{pattern}' on '{target_name}'")
        pat = (pattern or "").strip()
        if not pat:
            raise ValueError("Pattern cannot be empty")

        file_path = CONFIG_FILE
        data = self._load_json_config(file_path)
        if "permissions" not in data or not isinstance(data["permissions"], dict):
            data["permissions"] = {}
        perms = data["permissions"]

        if "patterns" not in perms or not isinstance(perms["patterns"], dict):
            perms["patterns"] = {}
        if target_name not in perms["patterns"] or not isinstance(perms["patterns"][target_name], list):
            perms["patterns"][target_name] = []

        existing = [r for r in perms["patterns"][target_name] if isinstance(r, dict) and r.get("pattern") != pat]
        perms["patterns"][target_name] = [{"pattern": pat, "action": raw_action}] + existing

        atomic_write_json(file_path, data)

    def get_effective_permissions(self) -> Dict[str, Any]:
        """Merges global config on top of DEFAULT_PERMISSIONS."""
        # 1. Base defaults
        merged = {
            "default": DEFAULT_PERMISSIONS.get("default", "ask"),
            "tools": dict(DEFAULT_PERMISSIONS.get("tools", {})),
            "patterns": dict(DEFAULT_PERMISSIONS.get("patterns", {})),
        }

        # 2. Global config (~/.johnston/config.json)
        global_cfg = self._load_json_config(CONFIG_FILE)
        global_perms = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
        _merge_perms(merged, global_perms)

        return merged

    def check_permission(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> PermissionDecision:
        """
        Evaluates permission for executing a tool.

        Returns a PermissionDecision(action, reason) where action is
        PermissionAction.ALLOW/ASK/DENY.
        """
        canonical_name = self._normalize_name(tool_name)
        # Fail-closed: an empty/absent tool name must never grant execution.
        if not canonical_name:
            return PermissionDecision(PermissionAction.DENY, "No tool name given")

        # 1. Check runtime session tool override
        if canonical_name in self.session_overrides:
            return PermissionDecision(
                PermissionAction(self.session_overrides[canonical_name]),
                f"Session override for '{canonical_name}'",
            )

        # 2. Check runtime session pattern overrides
        if canonical_name in self.session_pattern_overrides:
            decision = evaluate_pattern_rules(canonical_name, args, self.session_pattern_overrides[canonical_name])
            if decision is not None:
                return decision

        effective_perms = self.get_effective_permissions()

        # 3. Check pattern rules from config
        config_patterns = effective_perms.get("patterns", {}).get(canonical_name, [])
        if config_patterns:
            decision = evaluate_pattern_rules(canonical_name, args, config_patterns)
            if decision is not None:
                return decision

        # 4. Check tool-specific config
        tools_cfg = effective_perms.get("tools", {})
        if canonical_name in tools_cfg:
            return PermissionDecision(
                PermissionAction(tools_cfg[canonical_name]),
                f"Explicit tool permission for '{canonical_name}'",
            )

        # 5. MCP tools (not in the builtin registry) default to 'allow' so that
        #    connected servers work out of the box; explicit config still applies.
        if canonical_name not in self.builtin_tool_names:
            # Fail-closed: a broken raw 'default' config must never silently allow.
            global_cfg = self._load_json_config(CONFIG_FILE)
            perms_cfg = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
            raw_default = perms_cfg.get("default")
            if raw_default is not None:
                norm_default = normalize_action(raw_default)
                if norm_default in VALID_ACTIONS:
                    return PermissionDecision(
                        PermissionAction(norm_default),
                        f"MCP tool '{canonical_name}' applies configured default '{norm_default}'",
                    )
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Invalid default configured; MCP tool '{canonical_name}' fails closed",
                )
            return PermissionDecision(
                PermissionAction.ALLOW, f"MCP tool default for '{canonical_name}'"
            )

        # 6. Fallback to default
        default_action = effective_perms.get("default", "ask")
        # Fail-closed: any unexpected value becomes 'ask' (user confirmation), never silent 'allow'.
        return PermissionDecision(
            PermissionAction(normalize_action(default_action)),
            f"Default permission fallback for '{canonical_name}'",
        )

