from typing import Any, Callable, Dict, FrozenSet, List, Optional

from core.domain.defaults.config import DEFAULT_PERMISSIONS
from core.domain.policies.permission_policy import (
    _BUILTIN_TOOLS,
    VALID_ACTIONS,
    ExecutionMode,
    PermissionAction,
    PermissionDecision,
    _merge_perms,
    evaluate_pattern_rules,
    get_mode_baseline_action,
    normalize_action,
    normalize_execution_mode,
)
from core.infrastructure.platform.paths import CONFIG_FILE
from core.infrastructure.runtime.tool_name import normalize_tool_name


class PermissionManager:
    """Manages tool execution permissions (allow, ask, deny) and execution modes with config cascade."""

    VALID_ACTIONS = VALID_ACTIONS

    _instance: Optional["PermissionManager"] = None

    def __init__(
        self,
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
        builtin_tool_names: Optional[FrozenSet[str]] = None,
    ):
        self.session_overrides: Dict[str, str] = {}
        self.session_pattern_overrides: Dict[str, List[Dict[str, str]]] = {}
        self.session_mode: Optional[ExecutionMode] = None
        self.tool_name_normalizer = tool_name_normalizer
        self.builtin_tool_names = builtin_tool_names if builtin_tool_names is not None else _BUILTIN_TOOLS

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def execution_mode(self) -> ExecutionMode:
        """Returns the active execution mode (session override or config default)."""
        if self.session_mode is not None:
            return self.session_mode
        effective = self.get_effective_permissions()
        configured_mode = effective.get("mode")
        return normalize_execution_mode(configured_mode, default=ExecutionMode.REVIEW)

    def set_session_mode(self, mode: Any) -> ExecutionMode:
        """Sets a runtime session execution mode override ('review', 'edits', 'yolo')."""
        norm = normalize_execution_mode(mode)
        self.session_mode = norm
        return norm

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
        self.session_mode = None

    def _load_json_config(self, filepath: str) -> Dict[str, Any]:
        from core.models_catalog import cached_json_read

        data = cached_json_read(filepath, {})
        return data if isinstance(data, dict) else {}

    def get_effective_permissions(self) -> Dict[str, Any]:
        """Merges global config on top of DEFAULT_PERMISSIONS (cached by config snapshot)."""
        global_cfg = self._load_json_config(CONFIG_FILE)
        cfg_id = id(global_cfg)
        if (
            getattr(self, "_cached_effective_perms_id", None) == cfg_id
            and getattr(self, "_cached_effective_perms", None) is not None
        ):
            return self._cached_effective_perms

        # 1. Base defaults
        merged = {
            "mode": DEFAULT_PERMISSIONS.get("mode", "review"),
            "default": DEFAULT_PERMISSIONS.get("default", "allow"),
            "tools": dict(DEFAULT_PERMISSIONS.get("tools", {})),
            "patterns": dict(DEFAULT_PERMISSIONS.get("patterns", {})),
        }

        # 2. Global config (~/.johnston/config.json)
        global_perms = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
        if "mode" in global_perms and isinstance(global_perms["mode"], str):
            merged["mode"] = normalize_execution_mode(global_perms["mode"]).value

        _merge_perms(merged, global_perms)

        self._cached_effective_perms = merged
        self._cached_effective_perms_id = cfg_id
        return merged

    def check_permission(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> PermissionDecision:
        """
        Evaluates permission for executing a tool against the resolution cascade:
        1. Runtime session tool override
        2. Runtime session pattern overrides
        3. Config pattern rules (fail-closed DENY > ASK > ALLOW)
        4. Explicit user tool config in config.json
        5. Active Execution Mode baseline (review / edits / yolo)
        6. Global default fallback
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

        # 4. Check explicit tool config from user's config file
        global_cfg = self._load_json_config(CONFIG_FILE)
        global_perms = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
        explicit_tools = global_perms.get("tools", {}) if isinstance(global_perms.get("tools"), dict) else {}
        if canonical_name in explicit_tools:
            act_str = normalize_action(explicit_tools[canonical_name], default="ask")
            return PermissionDecision(
                PermissionAction(act_str),
                f"Explicit tool permission for '{canonical_name}'",
            )

        # Check if user explicitly configured a global default that fails closed or locks down to deny
        raw_default = global_perms.get("default")
        if raw_default is not None:
            norm_default = normalize_action(raw_default, default="ask")
            if norm_default == "deny":
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Configured global default 'deny' for '{canonical_name}'",
                )
            if isinstance(raw_default, str) and raw_default.strip().lower() not in VALID_ACTIONS:
                return PermissionDecision(
                    PermissionAction.ASK,
                    f"Invalid default configured; fails closed for '{canonical_name}'",
                )

        # 5. Active Execution Mode baseline
        active_mode = self.execution_mode
        is_mcp = canonical_name not in self.builtin_tool_names
        mode_action = get_mode_baseline_action(active_mode, canonical_name, is_mcp=is_mcp)
        return PermissionDecision(
            mode_action,
            f"Execution mode '{active_mode.value}' baseline for '{canonical_name}'",
        )


