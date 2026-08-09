import os
from typing import Any, Dict, Optional, Tuple

from core.config import CONFIG_FILE, PROJECT_PERMISSIONS_FILE
from core.defaults.config import DEFAULT_PERMISSIONS
from core.platform_utils import atomic_write_json, read_json
from core.shell_guard import analyze_shell_command


class PermissionManager:
    """Manages tool execution permissions (allow, ask, deny) with config cascade and shell_guard."""

    GROUPS = {
        "read": {"read", "ask_user", "update_plan", "manage_shell", "manage_subagent"},
        "write": {"create", "edit"},
        "net": {"web_fetch", "call_mcp"},
        "exec": {"shell", "invoke_subagent"},
    }

    VALID_ACTIONS = {"allow", "ask", "deny"}

    _instance: Optional["PermissionManager"] = None

    def __init__(self):
        self.session_overrides: Dict[str, str] = {}
        # Reverse map from tool to group
        self.tool_to_group: Dict[str, str] = {}
        for group, tools in self.GROUPS.items():
            for tool in tools:
                self.tool_to_group[tool] = group

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_group_for_tool(self, tool_name: str) -> Optional[str]:
        from tools.registry import ALIAS_MAP
        clean = (tool_name or "").strip().lower()
        canonical = ALIAS_MAP.get(clean, clean)
        return self.tool_to_group.get(canonical)

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
            from tools.registry import ALIAS_MAP
            clean = (tool_name or "").strip().lower()
            canonical = ALIAS_MAP.get(clean, clean)
            self.session_overrides[canonical] = normalized

    def clear_session_overrides(self) -> None:
        self.session_overrides.clear()

    def _load_json_config(self, filepath: str) -> Dict[str, Any]:
        data = read_json(filepath, {})
        return data if isinstance(data, dict) else {}

    def update_permission(
        self,
        target_type: str,
        target_name: str,
        action: str,
        project_dir: Optional[str] = None,
    ) -> None:
        """
        Updates a permission setting (target_type: 'group', 'tool' or 'shell_guard') to action.
        Raises ValueError on invalid target_type or action.
        Saves to project permissions file if project_dir is set, otherwise global config.
        """
        if target_type not in ("group", "tool", "shell_guard"):
            raise ValueError(f"Invalid target_type: '{target_type}'")

        target_name = (target_name or "").strip().lower()
        if target_type == "tool":
            from tools.registry import ALIAS_MAP
            target_name = ALIAS_MAP.get(target_name, target_name)

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

        if project_dir:
            file_path = os.path.join(project_dir, PROJECT_PERMISSIONS_FILE)
            data = self._load_json_config(file_path)
            if "permissions" not in data or not isinstance(data["permissions"], dict):
                data["permissions"] = {}
            perms = data["permissions"]
        else:
            file_path = CONFIG_FILE
            data = self._load_json_config(file_path)
            if "permissions" not in data or not isinstance(data["permissions"], dict):
                data["permissions"] = {}
            perms = data["permissions"]

        if target_type == "shell_guard":
            if "shell_guard" not in perms or not isinstance(perms["shell_guard"], dict):
                perms["shell_guard"] = {}
            perms["shell_guard"]["enabled"] = action in ("allow", "true", "enabled")
        else:
            section = "groups" if target_type == "group" else "tools"
            if section not in perms or not isinstance(perms[section], dict):
                perms[section] = {}
            perms[section][target_name] = action

        atomic_write_json(file_path, data)


    def get_effective_permissions(self, project_dir: Optional[str] = None) -> Dict[str, Any]:
        """Merges global and project permissions on top of DEFAULT_PERMISSIONS."""
        # 1. Base defaults
        merged = {
            "default": DEFAULT_PERMISSIONS.get("default", "ask"),
            "groups": dict(DEFAULT_PERMISSIONS.get("groups", {})),
            "tools": dict(DEFAULT_PERMISSIONS.get("tools", {})),
            "shell_guard": dict(DEFAULT_PERMISSIONS.get("shell_guard", {})),
        }

        # 2. Global config (~/.johnston/config.json)
        global_cfg = self._load_json_config(CONFIG_FILE)
        global_perms = global_cfg.get("permissions") if isinstance(global_cfg.get("permissions"), dict) else {}
        self._merge_perms(merged, global_perms)

        # 3. Project config (.johnston/permissions.json or .johnston/config.json)
        if project_dir:
            proj_perm_file = os.path.join(project_dir, PROJECT_PERMISSIONS_FILE)
            proj_cfg_file = os.path.join(project_dir, ".johnston", "config.json")

            proj_perms = {}
            if os.path.exists(proj_perm_file):
                proj_perms = self._load_json_config(proj_perm_file)
                if "permissions" in proj_perms and isinstance(proj_perms["permissions"], dict):
                    proj_perms = proj_perms["permissions"]
            elif os.path.exists(proj_cfg_file):
                cfg_data = self._load_json_config(proj_cfg_file)
                proj_perms = cfg_data.get("permissions") if isinstance(cfg_data.get("permissions"), dict) else {}

            self._merge_perms(merged, proj_perms)

        return merged

    def _merge_perms(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        if not override:
            return
        if "default" in override and isinstance(override["default"], str):
            base["default"] = self.normalize_action(override["default"])
        if "groups" in override and isinstance(override["groups"], dict):
            for g, act in override["groups"].items():
                if isinstance(act, str):
                    base["groups"][g.lower()] = self.normalize_action(act)
        if "tools" in override and isinstance(override["tools"], dict):
            for t, act in override["tools"].items():
                if isinstance(act, str):
                    base["tools"][t.lower()] = self.normalize_action(act)
        if "shell_guard" in override and isinstance(override["shell_guard"], dict):
            base["shell_guard"].update(override["shell_guard"])

    def check_permission(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        project_dir: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Evaluates permission for executing a tool.

        Returns (action, reason) where action is 'allow', 'ask', or 'deny'.
        """
        raw_tool = (tool_name or "").strip().lower()
        from tools.registry import ALIAS_MAP, normalize_tool_args
        canonical_name = ALIAS_MAP.get(raw_tool, raw_tool)
        norm_args = normalize_tool_args(canonical_name, args or {})

        effective_perms = self.get_effective_permissions(project_dir)

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
            sg_cfg = effective_perms.get("shell_guard", {})
            if sg_cfg.get("enabled", True) and self.session_overrides.get("shell_guard") != "allow":
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

        # 4. Check group-level config
        group = self.get_group_for_tool(canonical_name)
        groups_cfg = effective_perms.get("groups", {})
        if group and group in groups_cfg:
            return groups_cfg[group], f"Group permission '{group}' for tool '{canonical_name}'"

        # 5. Fallback to default
        default_action = effective_perms.get("default", "ask")
        # Fail-closed: any unexpected value becomes 'ask' (user confirmation), never silent 'allow'.
        return self.normalize_action(default_action), f"Default permission fallback for '{canonical_name}'"
