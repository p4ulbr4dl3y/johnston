import fnmatch
import os
from typing import Any, Callable, Dict, FrozenSet, List, Optional

from core.application.permission.permission_config import PermissionConfigStore
from core.domain.policies.permission_policy import (
    BUILTIN_TOOLS,
    VALID_ACTIONS,
    ExecutionMode,
    PermissionAction,
    PermissionDecision,
    evaluate_pattern_rules,
    evaluate_workspace_boundary,
    get_mode_baseline_action,
    has_unsafe_shell_syntax,
    normalize_execution_mode,
)
from core.infrastructure.platform.paths import CONFIG_FILE, LOGS_DIR, SECRETS_FILE
from core.infrastructure.runtime.git_utils import is_git_repository  # noqa: F401  (re-exported for patching)
from core.infrastructure.runtime.tool_name import normalize_tool_name

__all__ = ["PermissionManager", "CONFIG_FILE", "LOGS_DIR", "SECRETS_FILE"]


def _is_strict_ancestor(ancestor: str, target: str) -> bool:
    """True when ``target`` is a strict parent directory of ``ancestor``
    (e.g. '/' or a configured ``..`` entry). Such roots unboundedly widen the
    workspace, so they are ignored when resolving configured writable_roots."""
    if ancestor == target:
        return False
    try:
        return os.path.commonpath([ancestor, target]) == target
    except ValueError:
        return False


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
        self._config = PermissionConfigStore(
            current_project_dir=self.current_project_dir,
            workspace_roots=self.workspace_roots,
            tool_name_normalizer=tool_name_normalizer,
        )

    # ── effective-permissions cache (proxied to config store) ──────────────

    @property
    def _effective_cache(self):
        """Effective-permissions cache entry, proxied to the config store."""
        return self._config._effective_cache

    @_effective_cache.setter
    def _effective_cache(self, value) -> None:
        self._config._effective_cache = value

    @property
    def _effective_cache_by_key(self):
        """Effective-permissions per-key cache, proxied to the config store."""
        return self._config._effective_cache_by_key

    @_effective_cache_by_key.setter
    def _effective_cache_by_key(self, value) -> None:
        self._config._effective_cache_by_key = value

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

    # ── session overrides ───────────────────────────────────────────────────

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

    def clear_session_overrides(self) -> None:
        self.session_overrides.clear()
        self.session_pattern_overrides.clear()
        self.session_mode = None
        self._config.invalidate_cache()

    # ── workspace root in-memory ────────────────────────────────────────────

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
        pdir = os.path.realpath(os.path.abspath(project_dir or self.current_project_dir or os.getcwd()))
        for r in effective.get("writable_roots", []):
            if isinstance(r, str) and r.strip():
                val = r.strip()
                if not os.path.isabs(val):
                    norm = os.path.realpath(os.path.join(pdir, val))
                else:
                    norm = os.path.realpath(os.path.abspath(val))
                # Ignore configured roots that resolve to a strict ancestor of the
                # project (e.g. a bare '..' or '/'); they unboundedly widen the workspace.
                if norm and norm not in roots and not _is_strict_ancestor(pdir, norm):
                    roots.append(norm)
        return roots

    def set_project_dir(self, path: str) -> None:
        """Updates self.current_project_dir and sets primary workspace root."""
        norm = os.path.realpath(os.path.abspath(path))
        self.current_project_dir = norm
        self._config.current_project_dir = norm
        additional = [r for r in self.workspace_roots[1:] if r != norm]
        self.workspace_roots = [norm] + additional

    # ── normalization ───────────────────────────────────────────────────────

    def _normalize_name(self, tool_name: str) -> str:
        """Canonicalizes a tool name via the injected normalizer, falling back
        to the shared normalize_tool_name when none is provided."""
        if self.tool_name_normalizer:
            try:
                return self.tool_name_normalizer(tool_name)
            except Exception:
                return normalize_tool_name(tool_name)
        return normalize_tool_name(tool_name)

    @staticmethod
    def _config_tool_action(tools_cfg: Dict[str, Any], canonical_name: str) -> Optional[str]:
        """Resolves the explicit config action for a canonical tool name.

        Literal entries win; wildcard entries (``tool__*``) match via fnmatch
        and fall back fail-closed to 'deny' when any wildcard denies. Returns
        None when no config entry matches (caller falls back to defaults).
        """
        explicit = tools_cfg.get(canonical_name)
        if explicit is not None:
            return str(explicit) if isinstance(explicit, str) else None
        matched_acts = [
            act
            for pat, act in tools_cfg.items()
            if ("__" in pat and ("*" in pat or "?" in pat)) and fnmatch.fnmatch(canonical_name, pat)
        ]
        if not matched_acts:
            return None
        return "deny" if "deny" in matched_acts else matched_acts[0]

    # ── config persistence (delegates to _config) ───────────────────────────

    def ensure_gitignore(self, project_dir: Optional[str] = None) -> bool:
        """Ensures .johnston/config.local.json is listed in <project_dir>/.gitignore if git exists."""
        from core.application.permission.permission_config import ensure_gitignore as _ensure

        pdir = os.path.realpath(os.path.abspath(project_dir or self.current_project_dir or os.getcwd()))
        return _ensure(pdir)

    def save_workspace_root(
        self,
        path: str,
        scope: str = "auto",
        project_dir: Optional[str] = None,
    ) -> str:
        """Adds path to workspace roots and optionally persists to config.local.json or config.json.

        scope: 'session', 'local', 'project', or 'auto' (default: local if git, else project).
        Returns the resolved scope used ('session', 'local', or 'project').
        """
        abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        self.add_workspace_root(abs_path)
        return self._config.save_workspace_root(path, scope=scope, project_dir=project_dir)

    def remove_persisted_workspace_root(
        self,
        path: str,
        project_dir: Optional[str] = None,
    ) -> None:
        """Removes path from memory and from config.local.json / config.json if present."""
        abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        self.remove_workspace_root(abs_path)
        self._config.remove_persisted_workspace_root(path, project_dir=project_dir)

    def save_tool_permission(
        self,
        tool_name: str,
        action: str = "allow",
        scope: str = "auto",
        project_dir: Optional[str] = None,
    ) -> str:
        """Persists a tool permission override to config.local.json or config.json."""
        canonical = self._normalize_name(tool_name or "")
        if not canonical:
            return "session"
        act = (action or "").strip().lower()
        if act not in VALID_ACTIONS:
            return "session"

        self.set_session_override(canonical, act)
        return self._config.save_tool_permission(tool_name, action=action, scope=scope, project_dir=project_dir)

    def save_pattern_permission(
        self,
        tool_name: str,
        pattern: str,
        action: str = "allow",
        scope: str = "auto",
        project_dir: Optional[str] = None,
    ) -> str:
        """Persists a pattern permission override to config.local.json or config.json."""
        canonical = self._normalize_name(tool_name or "")
        pat = (pattern or "").strip()
        act = (action or "").strip().lower()
        if not canonical or not pat or act not in VALID_ACTIONS:
            return "session"

        self.set_session_pattern_override(canonical, pat, act)
        return self._config.save_pattern_permission(
            tool_name, pattern, action=action, scope=scope, project_dir=project_dir
        )

    # ── permission evaluation ───────────────────────────────────────────────

    def get_effective_permissions(self, project_dir: Optional[str] = None) -> Dict[str, Any]:
        """Merges global, project, and local config on top of DEFAULT_PERMISSIONS."""
        return self._config.get_effective_permissions(project_dir)

    def check_permission(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        project_dir: Optional[str] = None,
    ) -> PermissionDecision:
        """Evaluates permission for executing a tool against the resolution cascade:
        1. Config DENY patterns
        2. Workspace boundary check
        3. Runtime session tool override
        4. Runtime session pattern overrides
        5. Config pattern rules (non-DENY)
        6. Explicit tool permission from config
        7. Global default fallback (configured 'deny' locks down; junk fails closed to ASK)
        8. Active Execution Mode baseline
        """
        canonical_name = self._normalize_name(tool_name)
        # Fail-closed: an empty/absent tool name must never grant execution.
        if not canonical_name:
            return PermissionDecision(PermissionAction.DENY, "No tool name given")

        effective_perms = self.get_effective_permissions(project_dir)
        tools_cfg = effective_perms.get("tools", {})

        # 1. Config DENY patterns: an explicit admin-configured DENY pattern
        # must never be bypassed by session tool/pattern overrides — not even
        # an exact same-tool session override (wildcard denies are absolute).
        for pat, act in tools_cfg.items():
            if ("__" in pat and ("*" in pat or "?" in pat)) and act == "deny" and fnmatch.fnmatch(canonical_name, pat):
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Configured tool deny pattern '{pat}' matched '{canonical_name}'",
                )

        # 1b. Config explicit tool-level DENY: an admin-configured tool deny
        # (literal or wildcard) must never be bypassed by runtime session
        # *pattern* overrides (approval-path "allow once" grants) nor by a
        # session *wildcard* override. Only an exact session tool-level override
        # may lift it (documented cascade contract, see test_session_override_overrides_*).
        explicit_action = self._config_tool_action(tools_cfg, canonical_name)
        if explicit_action == "deny":
            has_session_tool_grant = canonical_name in self.session_overrides
            if not has_session_tool_grant:
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Configured tool permission for '{canonical_name}'",
                )

        config_patterns = effective_perms.get("patterns", {}).get(canonical_name, [])
        config_decision = evaluate_pattern_rules(canonical_name, args, config_patterns)
        if (
            config_decision is not None
            and config_decision.action == PermissionAction.DENY
        ):
            return config_decision

        # 2. Workspace boundary check: accessing files outside workspace
        # cannot be bypassed by session overrides or tool permissions in config.
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
            action = ws_decision.action if ws_decision.action == PermissionAction.DENY else outside_action
            return PermissionDecision(action, ws_decision.reason)

        # 2b. Dynamic/unsafe shell construct check:
        # Dynamic shell constructs (subshells, eval, script interpreter code injection)
        # cannot be bypassed by a tool-level session override unless in YOLO mode.
        if canonical_name == "shell" and args and isinstance(args, dict):
            cmd = args.get("command")
            if isinstance(cmd, str) and has_unsafe_shell_syntax(cmd):
                if self.execution_mode != ExecutionMode.YOLO:
                    return PermissionDecision(
                        PermissionAction.ASK,
                        f"Shell command contains dynamic/unsafe constructs: '{cmd.strip()}'",
                    )

        # 3. Runtime session tool override
        session_action = self.session_overrides.get(canonical_name)
        if session_action is None:
            matched_acts = [
                act
                for pat, act in self.session_overrides.items()
                if ("__" in pat and ("*" in pat or "?" in pat)) and fnmatch.fnmatch(canonical_name, pat)
            ]
            if matched_acts:
                session_action = "deny" if "deny" in matched_acts else matched_acts[0]
        if session_action is not None:
            return PermissionDecision(
                PermissionAction(session_action),
                f"Session override for '{canonical_name}'",
            )

        # 4. Runtime session pattern overrides
        decision = evaluate_pattern_rules(
            canonical_name, args, self.session_pattern_overrides.get(canonical_name, [])
        )
        if decision is not None:
            return decision

        # 5. Pattern rules from config
        if config_decision is not None:
            return config_decision

        # 6. Explicit tool permission from user's config file (normalized during merge)
        explicit_action = self._config_tool_action(tools_cfg, canonical_name)
        if explicit_action is not None:
            return PermissionDecision(
                PermissionAction(explicit_action),
                f"Explicit tool permission for '{canonical_name}'",
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

    # ── properties ──────────────────────────────────────────────────────────

    @property
    def execution_mode(self) -> ExecutionMode:
        """Returns the active execution mode (session override or config default)."""
        if self.session_mode is not None:
            return self.session_mode
        effective = self.get_effective_permissions()
        configured_mode = effective.get("mode")
        return normalize_execution_mode(configured_mode, default=ExecutionMode.REVIEW)
