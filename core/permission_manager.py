from typing import Any, Dict, FrozenSet, Optional, Tuple

from core.config import CONFIG_FILE
from core.defaults.config import DEFAULT_PERMISSIONS
from core.platform_utils import atomic_write_json, read_json
from core.shell_guard import analyze_shell_command

# Canonical names of builtin tools (kept out of tools/registry import to avoid
# a circular import: tools.registry imports tools.* which import core.*).
BUILTIN_TOOL_NAMES: FrozenSet[str] = frozenset(
    {
        "read",
        "create",
        "edit",
        "multi_edit",
        "shell",
        "ask_user",
        "update_plan",
        "manage_shell",
        "invoke_subagent",
        "manage_subagent",
        "web_fetch",
    }
)


class PermissionManager:
    """Manages tool execution permissions (allow, ask, deny) with config cascade and shell_guard."""

    VALID_ACTIONS = {"allow", "ask", "deny"}

    _instance: Optional["PermissionManager"] = None

    def __init__(self):
        self.session_overrides: Dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def normalize_action(action: str, default: str = "ask") -> str:
        """Normalizes an action to 'allow'/'ask'/'deny'. Invalid values fall back to default."""
        if isinstance(action, str):
            cleaned = action.strip().lower()
            if cleaned in PermissionManager.VALID_ACTIONS:
                return cleaned
        return default

    def set_session_override(self, tool_name: str, action: str) -> None:
        """Sets a runtime session override for a tool (e.g. 'allow', 'deny'). Invalid actions are ignored."""
        normalized = self.normalize_action(action)
        if normalized in self.VALID_ACTIONS:
            from tools.registry import normalize_tool_name

            canonical = normalize_tool_name(tool_name or "")
            self.session_overrides[canonical] = normalized

    def clear_session_overrides(self) -> None:
        self.session_overrides.clear()

    def _load_json_config(self, filepath: str) -> Dict[str, Any]:
        data = read_json(filepath, {})
        return data if isinstance(data, dict) else {}

    def update_permission(self, target_type: str, target_name: str, action: str) -> None:
        """
        Updates a global permission setting (target_type: 'tool' or 'shell_guard') to action.
        Raises ValueError on invalid target_type or action.
        Saves to the global config file (~/.johnston/config.json).
        """
        if target_type not in ("tool", "shell_guard"):
            raise ValueError(f"Invalid target_type: '{target_type}'")

        target_name = (target_name or "").strip().lower()
        if target_type == "tool":
            from tools.registry import normalize_tool_name

            target_name = normalize_tool_name(target_name)

        if target_type == "shell_guard":
            if action.lower() not in ("allow", "deny", "true", "false", "enabled", "disabled"):
                raise ValueError(f"Invalid shell_guard action: '{action}'")
        else:
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

        if target_type == "shell_guard":
            perms["shell_guard"] = action in ("allow", "true", "enabled")
        else:
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
            "shell_guard": DEFAULT_PERMISSIONS.get("shell_guard", True),
        }

        # 2. Global config (~/.johnston/config.json)
        global_cfg = self._load_json_config(CONFIG_FILE)
        global_perms = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
        self._merge_perms(merged, global_perms)

        return merged

    def _merge_perms(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        if not override:
            return
        if "default" in override and isinstance(override["default"], str):
            base["default"] = self.normalize_action(override["default"])
        if "tools" in override and isinstance(override["tools"], dict):
            for t, act in override["tools"].items():
                if isinstance(act, str):
                    base["tools"][t.lower()] = self.normalize_action(act)
        if "shell_guard" in override and isinstance(override["shell_guard"], bool):
            base["shell_guard"] = override["shell_guard"]

    def check_permission(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """
        Evaluates permission for executing a tool.

        Returns (action, reason) where action is 'allow', 'ask', or 'deny'.
        """
        raw_tool = (tool_name or "").strip().lower()
        from tools.registry import normalize_tool_args, normalize_tool_name

        canonical_name = normalize_tool_name(raw_tool)
        norm_args = normalize_tool_args(canonical_name, args or {})

        effective_perms = self.get_effective_permissions()

        # 1. Check shell_guard for 'shell' commands FIRST (security firewall)
        if canonical_name == "shell":
            command = (
                norm_args.get("command")
                or (args or {}).get("command")
                or (args or {}).get("cmd")
                or (args or {}).get("command_line")
                or (args or {}).get("CommandLine")
                or ""
            )
            sg_enabled = effective_perms.get("shell_guard", True)
            if sg_enabled and self.session_overrides.get("shell_guard") != "allow":
                is_safe, reason = analyze_shell_command(command)
                if not is_safe:
                    return "deny", f"Shell Guard flagged unsafe command: {reason}"

        # 2. Check runtime session overrides
        if canonical_name in self.session_overrides:
            return self.session_overrides[canonical_name], f"Session override for '{canonical_name}'"

        # 3. Check tool-specific config
        tools_cfg = effective_perms.get("tools", {})
        if canonical_name in tools_cfg:
            return tools_cfg[canonical_name], f"Explicit tool permission for '{canonical_name}'"

        # 4. MCP tools (not in the builtin registry) default to 'allow' so that
        #    connected servers work out of the box; explicit config still applies.
        if canonical_name not in BUILTIN_TOOL_NAMES:
            # Fail-closed: a broken raw 'default' config must never silently allow.
            raw_default = self._load_json_config(CONFIG_FILE).get("permissions", {}).get("default")
            if raw_default is not None and raw_default not in self.VALID_ACTIONS:
                return "ask", f"Invalid default configured; MCP tool '{canonical_name}' fails closed"
            return "allow", f"MCP tool default for '{canonical_name}'"

        # 5. Fallback to default
        default_action = effective_perms.get("default", "ask")
        # Fail-closed: any unexpected value becomes 'ask' (user confirmation), never silent 'allow'.
        return self.normalize_action(default_action), f"Default permission fallback for '{canonical_name}'"
