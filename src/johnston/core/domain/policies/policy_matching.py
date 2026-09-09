"""Pattern-matching helpers for the permission policy.

Moved verbatim from ``johnston.core.domain.policies.permission_policy``.
"""
import fnmatch
import os
import re
from typing import Any, Dict, List, Optional


def match_pattern(value: str, pattern: str) -> bool:
    """Matches a string value against a wildcard pattern."""
    if not pattern:
        return False
    return fnmatch.fnmatch(value.strip(), pattern.strip())


def match_path_pattern(path: str, pattern: str) -> bool:
    """Matches a file path against a pattern, normalizing path traversal and separators."""
    if not path or not pattern:
        return False
    pat = pattern.strip().replace("\\", "/")
    norm_p = os.path.normpath(path.strip()).replace("\\", "/")
    basename = os.path.basename(norm_p)

    # Match normalized path or basename
    if fnmatch.fnmatch(norm_p, pat) or fnmatch.fnmatch(basename, pat):
        return True

    # Suffix/subpath match (e.g. 'tests/**' matching '/a/b/tests/test_x.py')
    if pat.endswith("/**") or pat.endswith("/*"):
        prefix = pat.rstrip("/*")
        if prefix and (f"/{prefix}/" in norm_p or norm_p.startswith(f"{prefix}/") or norm_p == prefix):
            return True

    return False


PATH_ARG_KEYS = (
    "path",
    "AbsolutePath",
    "file_path",
    "target_file",
    "TargetFile",
    "source",
    "source_file",
    "src",
    "dest",
    "destination",
    "output_path",
    "output_file",
    "directory",
    "SearchDirectory",
)


def extract_tool_target_values(tool_name: str, args: Optional[Dict[str, Any]]) -> List[str]:
    """Extracts all target arguments (commands, paths, urls) for a given tool."""
    if not args or not isinstance(args, dict):
        return []
    canonical = (tool_name or "").strip().lower()
    if canonical == "shell":
        cmd = args.get("command")
        return [cmd.strip()] if isinstance(cmd, str) and cmd.strip() else []
    if canonical == "web_fetch":
        url = args.get("url")
        return [url.strip()] if isinstance(url, str) and url.strip() else []
    if canonical in ("create", "edit", "read", "view_file", "search"):
        targets: List[str] = []
        for key in PATH_ARG_KEYS:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                clean_val = val.strip()
                if clean_val not in targets:
                    targets.append(clean_val)
            elif isinstance(val, (list, tuple)):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        clean_item = item.strip()
                        if clean_item not in targets:
                            targets.append(clean_item)
        for list_key in ("paths", "files"):
            items = args.get(list_key)
            if isinstance(items, (list, tuple)):
                for item in items:
                    if isinstance(item, str) and item.strip():
                        clean_item = item.strip()
                        if clean_item not in targets:
                            targets.append(clean_item)
        return targets
    return []


def extract_tool_target_value(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extracts the primary target argument (command, path, or url) for a given tool."""
    targets = extract_tool_target_values(tool_name, args)
    return targets[0] if targets else None


def suggest_pattern(tool_name: str, args: Optional[Dict[str, Any]]) -> Optional[str]:
    """Suggests a pattern signature suitable for session pattern allow."""
    val = extract_tool_target_value(tool_name, args)
    if not val:
        return None
    canonical = (tool_name or "").strip().lower()
    if canonical == "shell":
        from johnston.core.domain.policies.policy_shell import extract_command_signature, has_unsafe_shell_syntax

        if has_unsafe_shell_syntax(val):
            return None
        return extract_command_signature(val)
    if canonical in ("create", "edit", "read", "view_file", "search"):
        # Suggest directory pattern or basename
        dirname = os.path.dirname(val)
        if dirname and dirname not in (".", "/"):
            return f"{dirname}/**"
        return val
    if canonical == "web_fetch":
        # Suggest domain pattern
        match = re.match(r"(https?://[^/]+)", val)
        if match:
            return f"{match.group(1)}/*"
        return f"{val}*"
    return None
