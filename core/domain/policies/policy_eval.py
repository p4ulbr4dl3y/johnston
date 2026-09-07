"""Pattern-rule evaluation for the permission policy.

Moved verbatim from ``core.domain.policies.permission_policy``.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.domain.policies.permission_policy import PermissionAction, PermissionDecision
from core.domain.policies.policy_matching import (
    extract_tool_target_value,
    extract_tool_target_values,
    match_path_pattern,
    match_pattern,
)
from core.domain.policies.policy_shell import (
    extract_command_signature,
    extract_shell_subcommands,
    has_unsafe_shell_syntax,
    normalize_action,
)


def _fail_closed_decision(matched: List[Tuple[PermissionAction, str]]) -> Optional[PermissionDecision]:
    """Picks a decision from collected (action, reason) matches.

    Applies the fail-closed priority DENY > ASK > ALLOW. Returns None when
    nothing matched, allowing callers to fall back to tool-level permission.
    """
    if not matched:
        return None
    for priority in (PermissionAction.DENY, PermissionAction.ASK):
        for act, reason in matched:
            if act == priority:
                return PermissionDecision(act, reason)
    return PermissionDecision(PermissionAction.ALLOW, matched[0][1])


def _iter_rules(rules: List[Dict[str, Any]]) -> List[Tuple[str, PermissionAction]]:
    """Normalizes raw rule dicts into valid (pattern, action) pairs."""
    pairs: List[Tuple[str, PermissionAction]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        pat = str(r.get("pattern", "")).strip()
        if not pat:
            continue
        pairs.append((pat, PermissionAction(normalize_action(r.get("action", "ask")))))
    return pairs


def _evaluate_shell_rules(cmd: str, rules: List[Dict[str, Any]]) -> Optional[PermissionDecision]:
    if has_unsafe_shell_syntax(cmd):
        return PermissionDecision(
            PermissionAction.ASK,
            f"Shell command contains dynamic/unsafe constructs: '{cmd}'",
        )
    subcmds = extract_shell_subcommands(cmd)
    if not subcmds:
        return None

    rule_pairs = _iter_rules(rules)
    for sub in subcmds:
        sig = extract_command_signature(sub)
        deny_hit = next(
            (
                pair
                for pair in rule_pairs
                if pair[1] == PermissionAction.DENY
                and (match_pattern(sub, pair[0]) or match_pattern(sig, pair[0]))
            ),
            None,
        )
        if deny_hit is not None:
            return PermissionDecision(
                PermissionAction.DENY,
                f"Subcommand '{sub}' matched deny pattern '{deny_hit[0]}'",
            )

    matched: List[Tuple[PermissionAction, str]] = []
    for sub in subcmds:
        sig = extract_command_signature(sub)
        hit = next((pair for pair in rule_pairs if match_pattern(sub, pair[0]) or match_pattern(sig, pair[0])), None)
        if hit is None:
            # If any subcommand is not covered by pattern rules, fall back to tool level
            return None
        pat, act = hit
        matched.append((act, f"Subcommand '{sub}' matched {act.value} pattern '{pat}'"))
    return _fail_closed_decision(matched)


def _evaluate_target_rules(
    target: str,
    rules: List[Dict[str, Any]],
    matcher: Callable[[str, str], bool],
    subject: str,
) -> Optional[PermissionDecision]:
    """Evaluates target-based rules (paths, urls) for a single primary target value."""
    matched = [
        (act, f"{subject} matched {act.value} pattern '{pat}'")
        for pat, act in _iter_rules(rules)
        if matcher(target, pat)
    ]
    return _fail_closed_decision(matched)


def evaluate_pattern_rules(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    rules: List[Dict[str, Any]],
) -> Optional[PermissionDecision]:
    """
    Evaluates pattern rules for a tool call.

    Returns PermissionDecision if any matching rule definitively decides the action,
    or None if no rule matches (allowing fallback to tool-level permission).
    """
    if not rules:
        return None

    canonical = (tool_name or "").strip().lower()

    if canonical == "shell":
        target = extract_tool_target_value(tool_name, args)
        if target is None:
            return None
        return _evaluate_shell_rules(target, rules)

    if canonical in ("create", "edit", "read", "view_file", "search"):
        targets = extract_tool_target_values(canonical, args)
        if not targets:
            return None
        decisions: List[PermissionDecision] = []
        for target in targets:
            dec = _evaluate_target_rules(target, rules, match_path_pattern, subject=f"Path '{target}'")
            if dec is None:
                return None  # At least one target is uncovered -> fallback to tool level
            if dec.action == PermissionAction.DENY:
                return dec  # Fail-closed immediately on any deny match
            decisions.append(dec)
        if any(d.action == PermissionAction.ASK for d in decisions):
            return next(d for d in decisions if d.action == PermissionAction.ASK)
        return decisions[0]

    if canonical == "web_fetch":
        target = extract_tool_target_value(tool_name, args)
        if target is None:
            return None
        return _evaluate_target_rules(target, rules, match_pattern, subject=f"URL '{target}'")

    return None
