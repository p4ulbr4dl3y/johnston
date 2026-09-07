"""Workspace-boundary and permission-merge helpers for the permission policy.

Moved verbatim from ``core.domain.policies.permission_policy``. Config/secrets
helpers are read dynamically from the facade module (``_pp``) so that tests
monkeypatching ``permission_policy.LOGS_DIR`` / ``permission_policy.SECRETS_FILE``
keep working.
"""
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence

from core.domain.policies import permission_policy as _pp
from core.domain.policies.permission_policy import PermissionAction, PermissionDecision
from core.domain.policies.policy_matching import extract_tool_target_values
from core.domain.policies.policy_shell import normalize_action


def is_path_within_workspace(
    target_path: str,
    workspace_roots: Sequence[str],
    allow_temp: bool = True,
    allowed_read_roots: Optional[Sequence[str]] = None,
) -> bool:
    """Checks whether a target path is contained within any of the workspace roots, system temp, or allowed read roots.

    Normalizes paths using realpath and abspath to protect against path traversal and symlink escapes.
    Safely handles missing or invalid paths and exceptions.
    """
    if not target_path or not isinstance(target_path, str) or not target_path.strip():
        return False

    try:
        norm_target = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(target_path.strip()))))
    except Exception:
        return False

    candidates: List[str] = []
    if workspace_roots:
        for r in workspace_roots:
            if isinstance(r, str) and r.strip():
                candidates.append(r.strip())

    for root in candidates:
        try:
            norm_root = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(root))))
            if os.path.commonpath([norm_target, norm_root]) == norm_root:
                return True
        except (ValueError, Exception):
            continue

    if allow_temp:
        # CONFIG_DIR (~/.johnston) is the application directory containing configuration,
        # history, and secrets. It must never be treated as a temporary scratch directory,
        # even if running in test environments where CONFIG_DIR is placed in a temp folder.
        is_in_config_dir = False
        try:
            cfg_dir = _pp.get_config_dir()
            if cfg_dir:
                norm_cfg = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(cfg_dir))))
                if os.path.commonpath([norm_target, norm_cfg]) == norm_cfg:
                    is_in_config_dir = True
        except Exception:
            pass

        if not is_in_config_dir:
            temp_candidates = [tempfile.gettempdir(), "/tmp", "/private/tmp"]
            for temp_dir in temp_candidates:
                if not temp_dir:
                    continue
                try:
                    norm_temp = os.path.normcase(os.path.realpath(os.path.abspath(temp_dir)))
                    if os.path.commonpath([norm_target, norm_temp]) == norm_temp:
                        return True
                except (ValueError, Exception):
                    continue

    if allowed_read_roots:
        for r_root in allowed_read_roots:
            if not r_root or not isinstance(r_root, str) or not r_root.strip():
                continue
            try:
                norm_r = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(r_root.strip()))))
                if os.path.commonpath([norm_target, norm_r]) == norm_r:
                    return True
            except (ValueError, Exception):
                continue

    return False


def evaluate_workspace_boundary(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    workspace_roots: Sequence[str],
    outside_action: PermissionAction = PermissionAction.ASK,
    allowed_read_roots: Optional[Sequence[str]] = None,
    secrets_file: Optional[str] = None,
) -> Optional[PermissionDecision]:
    """Evaluates whether a tool call accesses a path outside the permitted workspace roots,
    or attempts to access the protected secrets file.

    Extracts path for file tools (create, edit, read, view_file, search) or cwd/command for shell.
    Returns PermissionDecision if path is outside workspace roots or targets secrets, otherwise None.
    """
    canonical = (tool_name or "").strip().lower()

    if canonical == "shell":
        cmd = args.get("command") if isinstance(args, dict) else None
        cwd = args.get("cwd") if isinstance(args, dict) else None
        if cmd and _pp.is_secrets_shell_command(cmd, cwd=cwd, secrets_file=secrets_file):
            return PermissionDecision(
                PermissionAction.DENY,
                "Access to secrets file is denied",
            )
        if cwd and isinstance(cwd, str) and cwd.strip():
            if _pp.is_secrets_file(cwd.strip(), secrets_file=secrets_file):
                return PermissionDecision(
                    PermissionAction.DENY,
                    f"Access to secrets file '{cwd.strip()}' is denied",
                )
            if not is_path_within_workspace(cwd.strip(), workspace_roots):
                action = outside_action
                if isinstance(action, str):
                    try:
                        action = PermissionAction(action.lower())
                    except ValueError:
                        action = PermissionAction.ASK
                return PermissionDecision(action, f"Path '{cwd.strip()}' is outside workspace roots")
        return None

    targets: List[str] = []
    if canonical in ("create", "edit", "read", "view_file", "search"):
        targets = extract_tool_target_values(canonical, args)

    if not targets:
        return None

    # 1. Protection for SECRETS_FILE: always DENY across all file tools
    for raw_target in targets:
        target = raw_target.strip()
        if _pp.is_secrets_file(target, secrets_file=secrets_file):
            return PermissionDecision(
                PermissionAction.DENY,
                f"Access to secrets file '{target}' is denied",
            )

    # 2. Workspace boundary check with read-only root support (LOGS_DIR)
    effective_read_roots = None
    if canonical in _pp.READ_ONLY_TOOLS:
        effective_read_roots = allowed_read_roots if allowed_read_roots is not None else _pp.get_trusted_read_roots()

    for raw_target in targets:
        target = raw_target.strip()
        if not is_path_within_workspace(target, workspace_roots, allowed_read_roots=effective_read_roots):
            action = outside_action
            if isinstance(action, str):
                try:
                    action = PermissionAction(action.lower())
                except ValueError:
                    action = PermissionAction.ASK
            return PermissionDecision(action, f"Path '{target}' is outside workspace roots")

    return None


def merge_perms(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """Merges a permissions config override into base, in place.

    Tool actions are normalized to 'allow'/'ask'/'deny' (invalid values fail
    closed to 'ask'). The 'default' key is kept raw on purpose: consumers must
    distinguish a configured deny/lock-down from invalid junk that fails closed.
    """
    if not override:
        return
    if "default" in override and isinstance(override["default"], str):
        base["default"] = override["default"]
    if "tools" in override and isinstance(override["tools"], dict):
        if "tools" not in base or not isinstance(base["tools"], dict):
            base["tools"] = {}
        for t, act in override["tools"].items():
            if isinstance(act, str):
                base["tools"][t.lower()] = normalize_action(act)
    if "patterns" in override and isinstance(override["patterns"], dict):
        if "patterns" not in base or not isinstance(base["patterns"], dict):
            base["patterns"] = {}
        for t, rule_list in override["patterns"].items():
            if isinstance(rule_list, list):
                norm_rules = [
                    {"pattern": pat, "action": act}
                    for pat, act in (
                        (str(r["pattern"]).strip(), normalize_action(str(r.get("action", "ask"))))
                        for r in rule_list
                        if isinstance(r, dict) and "pattern" in r
                    )
                    if pat
                ]
                tool_key = t.lower()
                existing_rules = base["patterns"].get(tool_key, [])
                if not isinstance(existing_rules, list):
                    existing_rules = []

                rule_by_pattern: Dict[str, str] = {}
                for r in existing_rules:
                    if isinstance(r, dict) and "pattern" in r:
                        pat_key = str(r["pattern"]).strip()
                        if pat_key:
                            rule_by_pattern[pat_key] = normalize_action(str(r.get("action", "ask")))

                for r in norm_rules:
                    pat_key = r["pattern"]
                    act_val = r["action"]
                    # If base already has a DENY rule for this pattern, do not downgrade it
                    if rule_by_pattern.get(pat_key) == "deny" and act_val != "deny":
                        continue
                    rule_by_pattern[pat_key] = act_val

                base["patterns"][tool_key] = [
                    {"pattern": pat, "action": act}
                    for pat, act in rule_by_pattern.items()
                ]
    if "writable_roots" in override and isinstance(override["writable_roots"], list):
        if "writable_roots" not in base or not isinstance(base["writable_roots"], list):
            base["writable_roots"] = []
        for r in override["writable_roots"]:
            if isinstance(r, str) and r.strip() and r.strip() not in base["writable_roots"]:
                base["writable_roots"].append(r.strip())
    if "outside_workspace_action" in override:
        action_val = override["outside_workspace_action"]
        if isinstance(action_val, PermissionAction):
            action_val = action_val.value
        if isinstance(action_val, str):
            cleaned_action = action_val.strip().lower()
            if cleaned_action in ("ask", "deny"):
                base["outside_workspace_action"] = cleaned_action
