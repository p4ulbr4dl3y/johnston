"""Permission config persistence: JSON I/O, cache, and effective-permissions cascade."""
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.domain.defaults.config import DEFAULT_PERMISSIONS
from core.domain.policies.permission_policy import (
    VALID_ACTIONS,
    merge_perms,
    normalize_execution_mode,
)
from core.infrastructure.platform.platform_utils import cached_json_read
from core.infrastructure.runtime.tool_name import normalize_tool_name

__all__ = ["PermissionConfigStore", "ensure_gitignore"]

# Effective-permissions cache entry: (tuple of 3 file paths, tuple of 3 mtimes, merged perms).
_EffectiveCache = Tuple[
    Tuple[str, str, str],
    Tuple[Optional[float], Optional[float], Optional[float]],
    Dict[str, Any],
]


def _git_repo(pdir: str) -> bool:
    """Resolves is_git_repository via core.permission_manager so patches/tests
    targeting that module's attribute take effect."""
    from core.permission_manager import is_git_repository

    return is_git_repository(pdir)


def _file_mtime(path: str) -> Optional[float]:
    """Returns the file mtime used as a cache key, or None when unreadable/missing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def ensure_gitignore(project_dir: str) -> bool:
    """Ensures .johnston/config.local.json is listed in <project_dir>/.gitignore if git exists."""
    pdir = os.path.realpath(os.path.abspath(project_dir))
    has_git = (
        os.path.exists(os.path.join(pdir, ".git"))
        or os.path.exists(os.path.join(pdir, ".gitignore"))
        or _git_repo(pdir)
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


class PermissionConfigStore:
    """Manages permission config JSON I/O, effective-permissions caching, and persistence."""

    def __init__(
        self,
        current_project_dir: Optional[str],
        workspace_roots: List[str],
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.current_project_dir = current_project_dir
        self.workspace_roots = workspace_roots
        self.tool_name_normalizer = tool_name_normalizer
        self._effective_cache: Optional[_EffectiveCache] = None
        self._effective_cache_by_key: Dict[
            Tuple[Tuple[str, str, str], Tuple[Optional[float], Optional[float], Optional[float]]],
            Dict[str, Any],
        ] = {}

    # ── helpers ────────────────────────────────────────────────────────────

    def _normalize_name(self, tool_name: str) -> str:
        """Canonicalizes a tool name via the injected normalizer, falling back
        to the shared normalize_tool_name when none is provided."""
        if self.tool_name_normalizer:
            try:
                return self.tool_name_normalizer(tool_name)
            except Exception:
                return normalize_tool_name(tool_name)
        return normalize_tool_name(tool_name)

    def _resolve_pdir(self, project_dir: Optional[str] = None) -> str:
        return os.path.realpath(os.path.abspath(project_dir or self.current_project_dir or os.getcwd()))

    def _load_json_config(self, filepath: str) -> Dict[str, Any]:
        """Loads a JSON config file, returning a dict (empty dict on error/non-dict)."""
        data = cached_json_read(filepath, {})
        return data if isinstance(data, dict) else {}

    # ── public: workspace-root persistence ──────────────────────────────────

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
        if abs_path not in self.workspace_roots:
            self.workspace_roots.append(abs_path)

        if scope == "session":
            return "session"

        pdir = self._resolve_pdir(project_dir)
        if scope == "local":
            target_file = os.path.join(pdir, ".johnston", "config.local.json")
            actual_scope = "local"
        elif scope == "project":
            target_file = os.path.join(pdir, ".johnston", "config.json")
            actual_scope = "project"
        else:  # auto
            has_git = (
                os.path.exists(os.path.join(pdir, ".git"))
                or os.path.exists(os.path.join(pdir, ".gitignore"))
                or _git_repo(pdir)
            )
            if has_git:
                target_file = os.path.join(pdir, ".johnston", "config.local.json")
                actual_scope = "local"
            else:
                target_file = os.path.join(pdir, ".johnston", "config.json")
                actual_scope = "project"

        data: Dict[str, Any] = {}
        if os.path.isfile(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                data = {}

        perms = data.setdefault("permissions", {})
        if not isinstance(perms, dict):
            perms = {}
            data["permissions"] = perms

        writable_roots = perms.setdefault("writable_roots", [])
        if not isinstance(writable_roots, list):
            writable_roots = []
            perms["writable_roots"] = writable_roots

        if abs_path not in writable_roots:
            writable_roots.append(abs_path)

        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        if actual_scope == "local":
            ensure_gitignore(pdir)

        self.invalidate_cache()
        return actual_scope

    def remove_persisted_workspace_root(
        self,
        path: str,
        project_dir: Optional[str] = None,
    ) -> None:
        """Removes path from config.local.json / config.json if present."""
        abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(path)))

        pdir = self._resolve_pdir(project_dir)
        for filename in ("config.local.json", "config.json"):
            cfg_path = os.path.join(pdir, ".johnston", filename)
            if not os.path.isfile(cfg_path):
                continue
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                perms = data.get("permissions")
                if not isinstance(perms, dict):
                    continue
                roots = perms.get("writable_roots")
                if not isinstance(roots, list):
                    continue
                norm = os.path.realpath(os.path.abspath(abs_path))
                new_roots = [
                    r
                    for r in roots
                    if r != abs_path and (not isinstance(r, str) or os.path.realpath(os.path.abspath(r)) != norm)
                ]
                if len(new_roots) != len(roots):
                    perms["writable_roots"] = new_roots
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                        f.write("\n")
            except Exception:
                pass

        self.invalidate_cache()

    # ── public: tool/pattern permission persistence ─────────────────────────

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

        if scope == "session":
            return "session"

        pdir = self._resolve_pdir(project_dir)
        if scope == "local":
            target_file = os.path.join(pdir, ".johnston", "config.local.json")
            actual_scope = "local"
        elif scope == "project":
            target_file = os.path.join(pdir, ".johnston", "config.json")
            actual_scope = "project"
        else:
            has_git = (
                os.path.exists(os.path.join(pdir, ".git"))
                or os.path.exists(os.path.join(pdir, ".gitignore"))
                or _git_repo(pdir)
            )
            target_file = (
                os.path.join(pdir, ".johnston", "config.local.json")
                if has_git
                else os.path.join(pdir, ".johnston", "config.json")
            )
            actual_scope = "local" if has_git else "project"

        data: Dict[str, Any] = {}
        if os.path.isfile(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                data = {}

        perms = data.setdefault("permissions", {})
        if not isinstance(perms, dict):
            perms = {}
            data["permissions"] = perms

        tools = perms.setdefault("tools", {})
        if not isinstance(tools, dict):
            tools = {}
            perms["tools"] = tools
        tools[canonical] = act

        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        if actual_scope == "local":
            ensure_gitignore(pdir)

        self.invalidate_cache()
        return actual_scope

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

        if scope == "session":
            return "session"

        pdir = self._resolve_pdir(project_dir)
        if scope == "local":
            target_file = os.path.join(pdir, ".johnston", "config.local.json")
            actual_scope = "local"
        elif scope == "project":
            target_file = os.path.join(pdir, ".johnston", "config.json")
            actual_scope = "project"
        else:
            has_git = (
                os.path.exists(os.path.join(pdir, ".git"))
                or os.path.exists(os.path.join(pdir, ".gitignore"))
                or _git_repo(pdir)
            )
            target_file = (
                os.path.join(pdir, ".johnston", "config.local.json")
                if has_git
                else os.path.join(pdir, ".johnston", "config.json")
            )
            actual_scope = "local" if has_git else "project"

        data: Dict[str, Any] = {}
        if os.path.isfile(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                data = {}

        perms = data.setdefault("permissions", {})
        if not isinstance(perms, dict):
            perms = {}
            data["permissions"] = perms

        patterns_map = perms.setdefault("patterns", {})
        if not isinstance(patterns_map, dict):
            patterns_map = {}
            perms["patterns"] = patterns_map

        rules = patterns_map.setdefault(canonical, [])
        if not isinstance(rules, list):
            rules = []
            patterns_map[canonical] = rules

        rules = [r for r in rules if not (isinstance(r, dict) and r.get("pattern") == pat)]
        rules.insert(0, {"pattern": pat, "action": act})
        patterns_map[canonical] = rules

        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        if actual_scope == "local":
            ensure_gitignore(pdir)

        self.invalidate_cache()
        return actual_scope

    # ── public: cache management ────────────────────────────────────────────

    def invalidate_cache(self) -> None:
        """Clears the effective-permissions cache."""
        self._effective_cache = None
        self._effective_cache_by_key.clear()

    # ── public: effective permissions cascade ───────────────────────────────

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
        pdir = self._resolve_pdir(project_dir)

        # Resolve CONFIG_FILE dynamically via the orchestrator module so that
        # patches/tests targeting core.permission_manager.CONFIG_FILE take effect.
        from core.permission_manager import CONFIG_FILE as global_path
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
            ensure_gitignore(pdir)

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
