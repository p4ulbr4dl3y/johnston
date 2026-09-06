import os
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from core.domain.defaults.config import DEFAULT_PERMISSIONS
from core.domain.policies.permission_policy import (
    BUILTIN_TOOLS,
    VALID_ACTIONS,
    ExecutionMode,
    PermissionAction,
    PermissionDecision,
    evaluate_pattern_rules,
    evaluate_workspace_boundary,
    get_mode_baseline_action,
    merge_perms,
    normalize_execution_mode,
)
from core.infrastructure.platform.paths import CONFIG_FILE
from core.infrastructure.platform.platform_utils import cached_json_read
from core.infrastructure.runtime.git_utils import is_git_repository
from core.infrastructure.runtime.tool_name import normalize_tool_name

# Effective-permissions cache entry: (tuple of 3 file paths, tuple of 3 mtimes, merged perms).
_EffectiveCache = Tuple[
    Tuple[str, str, str],
    Tuple[Optional[float], Optional[float], Optional[float]],
    Dict[str, Any],
]


def _file_mtime(path: str) -> Optional[float]:
    """Returns the file mtime used as a cache key, or None when unreadable/missing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


class PermissionManager:
    """Manages tool execution permissions (allow, ask, deny) and execution modes with config cascade."""

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
        self.builtin_tool_names = builtin_tool_names if builtin_tool_names is not None else BUILTIN_TOOLS
        self.current_project_dir: Optional[str] = None
        self.workspace_roots: List[str] = [os.path.realpath(os.getcwd())]
        self._effective_cache: Optional[_EffectiveCache] = None
        self._effective_cache_by_key: Dict[
            Tuple[Tuple[str, str, str], Tuple[Optional[float], Optional[float], Optional[float]]],
            Dict[str, Any],
        ] = {}

    @classmethod
    def get_instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def configure_instance(
        cls,
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
        builtin_tool_names: Optional[FrozenSet[str]] = None,
    ) -> "PermissionManager":
        """Replaces the process-wide singleton with a configured instance.

        Composition-root hook for dependency wiring; keeps private state
        encapsulated instead of having callers assign ``cls._instance``.
        """
        cls._instance = cls(
            tool_name_normalizer=tool_name_normalizer,
            builtin_tool_names=builtin_tool_names,
        )
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
        if raw not in VALID_ACTIONS:
            return  # silently ignore (consistent with docstring)
        canonical = self._normalize_name(tool_name or "")
        self.session_overrides[canonical] = raw

    def set_session_pattern_override(self, tool_name: str, pattern: str, action: str) -> None:
        """Sets a runtime session pattern override for a tool."""
        raw = (action or "").strip().lower()
        if raw not in VALID_ACTIONS:
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

    def add_workspace_root(self, path: str) -> None:
        """Normalizes path via os.path.realpath(os.path.abspath(path)) and appends if not present."""
        norm = os.path.realpath(os.path.abspath(path))
        if norm not in self.workspace_roots:
            self.workspace_roots.append(norm)

    def remove_workspace_root(self, path: str) -> None:
        """Removes normalized path from workspace roots."""
        norm = os.path.realpath(os.path.abspath(path))
        if norm in self.workspace_roots:
            self.workspace_roots.remove(norm)

    def get_workspace_roots(self, project_dir: Optional[str] = None) -> List[str]:
        """Combines self.workspace_roots with any configured writable_roots from get_effective_permissions()."""
        roots = list(self.workspace_roots)
        effective = self.get_effective_permissions(project_dir)
        for r in effective.get("writable_roots", []):
            if isinstance(r, str) and r.strip():
                norm = os.path.realpath(os.path.abspath(r.strip()))
                if norm not in roots:
                    roots.append(norm)
        return roots

    def set_project_dir(self, path: str) -> None:
        """Updates self.current_project_dir and sets primary workspace root."""
        norm = os.path.realpath(os.path.abspath(path))
        self.current_project_dir = norm
        additional = [r for r in self.workspace_roots[1:] if r != norm]
        self.workspace_roots = [norm] + additional

    def ensure_gitignore(self, project_dir: Optional[str] = None) -> bool:
        """Ensures .johnston/config.local.json is listed in <project_dir>/.gitignore if git exists."""
        pdir = os.path.realpath(os.path.abspath(project_dir or self.current_project_dir or os.getcwd()))
        has_git = (
            os.path.exists(os.path.join(pdir, ".git"))
            or os.path.exists(os.path.join(pdir, ".gitignore"))
            or is_git_repository(pdir)
        )
        if not has_git:
            return False

        gitignore_path = os.path.join(pdir, ".gitignore")
        target_entry = ".johnston/config.local.json"
        content = ""
        if os.path.exists(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                return False

            lines = [line.strip() for line in content.splitlines()]
            if target_entry in lines or f"/{target_entry}" in lines:
                return True

        try:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write(f"{target_entry}\n")
            return True
        except OSError:
            return False

    def clear_session_overrides(self) -> None:
        self.session_overrides.clear()
        self.session_pattern_overrides.clear()
        self.session_mode = None
        self._effective_cache = None
        self._effective_cache_by_key.clear()

    def _load_json_config(self, filepath: str) -> Dict[str, Any]:
        data = cached_json_read(filepath, {})
        return data if isinstance(data, dict) else {}

    def get_effective_permissions(self, project_dir: Optional[str] = None) -> Dict[str, Any]:
        """Merges global, project, and local config on top of DEFAULT_PERMISSIONS.

        Cascade order:
        1. Base DEFAULT_PERMISSIONS
        2. Global config: CONFIG_FILE (~/.johnston/config.json)
        3. Project shared config: <project_dir>/.johnston/config.json
        4. Project local config: <project_dir>/.johnston/config.local.json

        If project_dir is None, defaults to self.current_project_dir or os.getcwd().
        Caches effective permissions keyed by all three file paths and their mtimes.
        """
        pdir = os.path.realpath(os.path.abspath(project_dir or self.current_project_dir or os.getcwd()))

        global_path = CONFIG_FILE
        shared_path = os.path.join(pdir, ".johnston", "config.json")
        local_path = os.path.join(pdir, ".johnston", "config.local.json")

        global_mtime = _file_mtime(global_path)
        shared_mtime = _file_mtime(shared_path)
        local_mtime = _file_mtime(local_path)

        paths = (global_path, shared_path, local_path)
        stamps = (global_mtime, shared_mtime, local_mtime)
        cache_key = (paths, stamps)

        if (
            self._effective_cache is not None
            and self._effective_cache[0] == paths
            and self._effective_cache[1] == stamps
        ):
            return self._effective_cache[2]

        if cache_key in self._effective_cache_by_key:
            merged = self._effective_cache_by_key[cache_key]
            self._effective_cache = (paths, stamps, merged)
            return merged

        # Auto-gitignore helper: when <project_dir>/.johnston/config.local.json exists or is updated,
        # ensure .johnston/config.local.json is listed in <project_dir>/.gitignore if git exists.
        if os.path.exists(local_path):
            self.ensure_gitignore(pdir)

        # 1. Base defaults
        merged: Dict[str, Any] = {
            "mode": DEFAULT_PERMISSIONS.get("mode", "review"),
            "default": DEFAULT_PERMISSIONS.get("default", "allow"),
            "tools": dict(DEFAULT_PERMISSIONS.get("tools", {})),
            "patterns": {k: list(v) for k, v in DEFAULT_PERMISSIONS.get("patterns", {}).items()},
            "writable_roots": list(DEFAULT_PERMISSIONS.get("writable_roots", [])),
            "outside_workspace_action": DEFAULT_PERMISSIONS.get("outside_workspace_action", "ask"),
        }

        # 2. Global config, 3. Project shared config, 4. Project local config
        for cfg_path in (global_path, shared_path, local_path):
            cfg_data = self._load_json_config(cfg_path)
            if not cfg_data:
                continue
            perms = cfg_data.get("permissions") if isinstance(cfg_data.get("permissions"), dict) else cfg_data
            if "mode" in perms and isinstance(perms["mode"], str):
                merged["mode"] = normalize_execution_mode(perms["mode"]).value
            elif "mode" in cfg_data and isinstance(cfg_data["mode"], str):
                merged["mode"] = normalize_execution_mode(cfg_data["mode"]).value
            merge_perms(merged, perms)

        self._effective_cache = (paths, stamps, merged)
        self._effective_cache_by_key[cache_key] = merged
        return merged

    def check_permission(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        project_dir: Optional[str] = None,
    ) -> PermissionDecision:
        """Evaluates permission for executing a tool against the resolution cascade:
        1. Runtime session tool override
        2. Config DENY patterns
        3. Runtime session pattern overrides
        4. Config pattern rules
        5. Explicit tool permission from config
        --> Check workspace boundary
        6. Global default fallback (configured 'deny' locks down; junk fails closed to ASK)
        7. Active Execution Mode baseline
        """
        canonical_name = self._normalize_name(tool_name)
        # Fail-closed: an empty/absent tool name must never grant execution.
        if not canonical_name:
            return PermissionDecision(PermissionAction.DENY, "No tool name given")

        # 1. Runtime session tool override
        session_action = self.session_overrides.get(canonical_name)
        if session_action is not None:
            return PermissionDecision(
                PermissionAction(session_action),
                f"Session override for '{canonical_name}'",
            )

        effective_perms = self.get_effective_permissions(project_dir)

        # 2. Config DENY patterns: a session-scoped allow granted via
        # the confirmation dialog must never bypass an explicit admin-configured
        # DENY. Session allows may only override config ASK/ALLOW rules.
        config_patterns = effective_perms.get("patterns", {}).get(canonical_name, [])
        config_decision = evaluate_pattern_rules(canonical_name, args, config_patterns)
        if (
            config_decision is not None
            and config_decision.action == PermissionAction.DENY
        ):
            return config_decision

        # 3. Runtime session pattern overrides
        decision = evaluate_pattern_rules(
            canonical_name, args, self.session_pattern_overrides.get(canonical_name, [])
        )
        if decision is not None:
            return decision

        # 4. Pattern rules from config
        if config_decision is not None:
            return config_decision

        # 5. Explicit tool permission from user's config file (normalized during merge)
        explicit_action = effective_perms.get("tools", {}).get(canonical_name)
        if explicit_action is not None:
            return PermissionDecision(
                PermissionAction(explicit_action),
                f"Explicit tool permission for '{canonical_name}'",
            )

        # Check workspace boundary
        raw_outside_action = effective_perms.get("outside_workspace_action", "ask")
        outside_action = (
            PermissionAction.DENY
            if str(raw_outside_action).lower() == "deny"
            else PermissionAction.ASK
        )
        ws_decision = evaluate_workspace_boundary(
            canonical_name,
            args,
            self.get_workspace_roots(project_dir),
            outside_action=outside_action,
        )
        if ws_decision is not None:
            active_mode = self.execution_mode
            if active_mode in (ExecutionMode.EDITS, ExecutionMode.YOLO):
                return PermissionDecision(
                    outside_action,
                    f"Path outside workspace roots: {ws_decision.reason}",
                )
            if active_mode == ExecutionMode.REVIEW and outside_action == PermissionAction.DENY:
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Path outside workspace roots: {ws_decision.reason}",
                )

        # Configured global default: only tightens ('deny') or fails closed;
        # valid allow/ask fall through to the mode baseline.
        raw_default = effective_perms.get("default")
        if isinstance(raw_default, str):
            lowered = raw_default.strip().lower()
            if lowered == "deny":
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Configured global default 'deny' for '{canonical_name}'",
                )
            if lowered not in VALID_ACTIONS:
                return PermissionDecision(
                    PermissionAction.ASK,
                    f"Invalid default configured; fails closed for '{canonical_name}'",
                )

        # 6. Active Execution Mode baseline
        active_mode = self.execution_mode
        is_mcp = canonical_name not in self.builtin_tool_names
        mode_action = get_mode_baseline_action(active_mode, canonical_name, is_mcp=is_mcp)
        return PermissionDecision(
            mode_action,
            f"Execution mode '{active_mode.value}' baseline for '{canonical_name}'",
        )
