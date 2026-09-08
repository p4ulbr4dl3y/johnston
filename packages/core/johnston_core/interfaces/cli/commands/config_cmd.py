"""CLI config command for inspecting and modifying application settings."""
from __future__ import annotations

import json
import math
import sys
import types
import typing
from dataclasses import fields
from typing import Any, Dict, Optional, Tuple, Type, get_args, get_origin

from johnston_core.infrastructure.config.settings import (
    LLMSettings,
    SandboxSettings,
    StorageSettings,
    SubagentsSettings,
    ToolsSettings,
    UISettings,
    get_settings,
    load_settings,
    save_settings,
)
from johnston_core.infrastructure.platform import paths
from johnston_core.infrastructure.platform.platform_utils import read_json
from johnston_core.interfaces.cli.formatter import format_table

SECTION_MAP: Dict[str, Type[Any]] = {
    "sandbox": SandboxSettings,
    "llm": LLMSettings,
    "tools": ToolsSettings,
    "subagents": SubagentsSettings,
    "ui": UISettings,
    "storage": StorageSettings,
}

TOP_LEVEL_FIELDS: Dict[str, Any] = {
    "model": Optional[str],
    "theme": Optional[str],
}

MIN_CONSTRAINTS: Dict[str, float] = {
    "llm.context_limit": 1000,
    "llm.auto_compact_token_limit": 1000,
    "llm.compaction_threshold_ratio": 0.1,
    "llm.compaction_summarize_ratio": 0.1,
    "llm.compaction_user_budget": 100,
    "llm.stream_timeout": 0.1,
    "llm.chunk_timeout": 0.1,
    "llm.default_max_tokens": 1,
    "llm.max_retries": 0,
    "llm.retry_delay": 0.0,
    "llm.retry_backoff": 1.0,
    "llm.max_retry_delay": 0.0,
    "llm.cb_failure_threshold": 1,
    "llm.cb_cooldown_seconds": 0.0,
    "llm.auto_title_timeout": 0.1,
    "llm.auto_title_max_len": 10,
    "llm.catalog_cache_ttl": 0.0,
    "llm.agent_md_max_chars": 1000,
    "tools.shell_default_timeout": 0.1,
    "tools.shell_max_cap": 0.1,
    "tools.shell_idle_timeout": 0,
    "tools.max_shell_output_chars": 100,
    "tools.max_tool_output_chars": 100,
    "tools.max_tool_payload_bytes": 1024,
    "tools.max_snapshot_log_bytes": 1024,
    "tools.mcp_call_timeout": 0.1,
    "tools.mcp_init_timeout": 0.1,
    "tools.web_fetch_timeout": 0.1,
    "tools.read_line_window": 10,
    "tools.max_dir_entries": 5,
    "tools.doc_conversion_timeout": 0.5,
    "tools.max_image_dimension": 128,
    "tools.image_dimension_low": 128,
    "tools.image_dimension_high": 128,
    "tools.image_png_keep_bytes": 1024,
    "tools.max_doc_cache": 1,
    "tools.doc_cache_ttl": 0.0,
    "tools.line_count_cache_max": 1,
    "tools.dns_cache_ttl": 0.0,
    "tools.dns_cache_max": 1,
    "tools.mcp_miss_ttl": 0.0,
    "tools.mcp_miss_max": 1,
    "tools.shell_stream_buffer_bytes": 1024,
    "subagents.max_concurrent": 1,
    "subagents.max_result_chars": 100,
    "subagents.worktree_timeout": 0.1,
    "subagents.auto_compact_token_limit": 1000,
    "ui.max_prompt_history": 1,
    "ui.max_chat_input_lines": 2,
    "ui.stream_flush_interval": 0.0,
    "ui.chat_page_size": 1,
    "ui.paste_line_threshold": 1,
    "ui.autocomplete_max_files": 10,
    "storage.max_log_bytes": 1024,
    "storage.max_log_age_days": 0,
    "storage.disk_cache_ttl": 0.0,
}


def _get_field_type(cls: Type[Any], field_name: str) -> Any:
    try:
        hints = typing.get_type_hints(cls)
        if field_name in hints:
            return hints[field_name]
    except Exception:
        pass
    for f in fields(cls):
        if f.name == field_name:
            return f.type
    return str


def resolve_key(key: str) -> Tuple[str, Optional[str], str, Any]:
    """Resolve a user-provided key to (canonical_key, section_name, field_name, field_type).

    Raises KeyError if key is not found or ambiguous.
    """
    cleaned = key.strip()
    if cleaned in TOP_LEVEL_FIELDS:
        return cleaned, None, cleaned, TOP_LEVEL_FIELDS[cleaned]

    if "." in cleaned:
        sec, field_name = cleaned.split(".", 1)
        if sec in SECTION_MAP:
            cls = SECTION_MAP[sec]
            for f in fields(cls):
                if f.name == field_name:
                    return f"{sec}.{field_name}", sec, field_name, _get_field_type(cls, field_name)
        raise KeyError(f"Unknown configuration key '{cleaned}'")

    matches: list[Tuple[str, Optional[str], str, Any]] = []
    for sec, cls in SECTION_MAP.items():
        for f in fields(cls):
            if f.name == cleaned:
                matches.append((f"{sec}.{f.name}", sec, f.name, _get_field_type(cls, f.name)))

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        options = ", ".join(m[0] for m in matches)
        raise KeyError(f"Ambiguous key '{cleaned}'. Please specify section: {options}")

    raise KeyError(f"Unknown configuration key '{cleaned}'")


def _normalize_type(field_type: Any) -> Tuple[bool, Any]:
    """Extract (is_optional, base_type) from a type hint or string annotation."""
    if isinstance(field_type, str):
        is_opt = "Optional" in field_type or "None" in field_type
        low = field_type.lower()
        if "dict" in low:
            return is_opt, dict
        if "list" in low:
            return is_opt, list
        if "bool" in low:
            return is_opt, bool
        if "int" in low:
            return is_opt, int
        if "float" in low:
            return is_opt, float
        return is_opt, str

    origin = get_origin(field_type)
    is_opt = False
    if origin is typing.Union or (hasattr(types, "UnionType") and origin is types.UnionType):
        args = get_args(field_type)
        is_opt = type(None) in args
        non_none = [t for t in args if t is not type(None)]
        field_type = non_none[0] if non_none else str
        origin = get_origin(field_type)

    if origin in (dict, list):
        return is_opt, origin
    if field_type in (dict, list):
        return is_opt, field_type

    if origin is not None:
        args = get_args(field_type)
        non_none = [t for t in args if t is not type(None)]
        base = non_none[0] if non_none else str
        return is_opt, base

    return is_opt, field_type


def _parse_and_validate(raw_val: str, field_type: Any, canonical_key: str) -> Any:
    """Parse raw string into typed value, validating bounds and format."""
    trimmed = raw_val.strip()
    is_opt, target_type = _normalize_type(field_type)

    if is_opt and trimmed.lower() in ("none", "null", ""):
        return None

    if target_type is dict or target_type is list or get_origin(target_type) in (dict, list):
        expected_origin = dict if (target_type is dict or get_origin(target_type) is dict) else list
        try:
            val = json.loads(trimmed)
        except Exception:
            kind = "JSON object (dict)" if expected_origin is dict else "JSON array (list)"
            raise ValueError(f"Invalid JSON for '{canonical_key}'. Expected a {kind}.")
        if not isinstance(val, expected_origin):
            kind = "JSON object (dict)" if expected_origin is dict else "JSON array (list)"
            raise ValueError(f"Invalid type for '{canonical_key}'. Expected a {kind}.")
        return val

    if target_type is bool:
        low = trimmed.lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"Invalid boolean value '{raw_val}' for '{canonical_key}'. Expected true/false.")

    if target_type is int:
        try:
            val = int(trimmed)
        except ValueError:
            raise ValueError(f"Invalid integer value '{raw_val}' for '{canonical_key}'.")
        min_v = MIN_CONSTRAINTS.get(canonical_key)
        if min_v is not None and val < min_v:
            raise ValueError(f"Value for '{canonical_key}' must be at least {int(min_v)}.")
        return val

    if target_type is float:
        try:
            val = float(trimmed)
            if math.isnan(val) or math.isinf(val):
                raise ValueError
        except ValueError:
            raise ValueError(f"Invalid float value '{raw_val}' for '{canonical_key}'.")
        min_v = MIN_CONSTRAINTS.get(canonical_key)
        if min_v is not None and val < min_v:
            raise ValueError(f"Value for '{canonical_key}' must be at least {min_v}.")
        return val

    if target_type is str:
        return trimmed

    return trimmed


def list_config(config_file: Optional[str] = None, as_json: bool = False) -> int:
    """List all settings with section/key, current value, and source (config vs default)."""
    target_file = config_file or paths.CONFIG_FILE
    settings = get_settings(target_file)
    raw_config = read_json(target_file, default={})
    if not isinstance(raw_config, dict):
        raw_config = {}

    rows: list[list[str]] = []

    for key in sorted(TOP_LEVEL_FIELDS.keys()):
        val = getattr(settings, key, None)
        source = "config" if key in raw_config and raw_config[key] is not None else "default"
        rows.append([key, str(val if val is not None else "None"), source])

    for sec_name, cls in SECTION_MAP.items():
        sec_obj = getattr(settings, sec_name, None)
        sec_raw = raw_config.get(sec_name) if isinstance(raw_config.get(sec_name), dict) else {}
        for f in sorted(fields(cls), key=lambda x: x.name):
            f_key = f"{sec_name}.{f.name}"
            val = getattr(sec_obj, f.name, None) if sec_obj is not None else None
            source = "config" if f.name in sec_raw else "default"
            rows.append([f_key, str(val if val is not None else "None"), source])

    if as_json:
        data = [
            {"setting": row[0], "value": row[1], "source": row[2]}
            for row in rows
        ]
        print(json.dumps(data, indent=2))
        return 0

    print(format_table(["Setting", "Value", "Source"], rows))
    return 0


def get_config(key: str, config_file: Optional[str] = None, as_json: bool = False) -> int:
    """Get value of a single setting."""
    try:
        canonical_key, sec, field_name, _ = resolve_key(key)
    except KeyError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    target_file = config_file or paths.CONFIG_FILE
    settings = get_settings(target_file)
    if sec is None:
        val = getattr(settings, field_name, None)
    else:
        sec_obj = getattr(settings, sec, None)
        val = getattr(sec_obj, field_name, None) if sec_obj is not None else None

    if as_json:
        print(json.dumps({canonical_key: val}, indent=2))
        return 0

    print(str(val if val is not None else "None"))
    return 0


def set_config(key: str, value: str, config_file: Optional[str] = None) -> int:
    """Set value of a configuration setting."""
    try:
        canonical_key, sec, field_name, field_type = resolve_key(key)
    except KeyError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    try:
        parsed = _parse_and_validate(value, field_type, canonical_key)
    except ValueError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    target_file = config_file or paths.CONFIG_FILE
    settings = load_settings(target_file)
    if sec is None:
        setattr(settings, field_name, parsed)
    else:
        sec_obj = getattr(settings, sec)
        setattr(sec_obj, field_name, parsed)

    save_settings(settings, target_file)
    print(f"Set '{canonical_key}' to '{parsed}'.")
    return 0


def unset_config(key: str, config_file: Optional[str] = None) -> int:
    """Reset a configuration setting to its default value."""
    try:
        canonical_key, sec, field_name, _ = resolve_key(key)
    except KeyError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    target_file = config_file or paths.CONFIG_FILE
    settings = load_settings(target_file)
    if sec is None:
        setattr(settings, field_name, None)
        default_val: Any = None
    else:
        default_inst = SECTION_MAP[sec]()
        default_val = getattr(default_inst, field_name)
        sec_obj = getattr(settings, sec)
        setattr(sec_obj, field_name, default_val)

    save_settings(settings, target_file)
    print(f"Unset '{canonical_key}' (reset to default: {default_val}).")
    return 0


def run_config(args: Any = None, config_file: Optional[str] = None) -> int:
    """Execute config subcommand based on parsed arguments."""
    action = getattr(args, "config_action", None) if args is not None else None
    cfg_file = getattr(args, "config_file", None) or config_file

    as_json = bool(getattr(args, "json", False))

    if action is None or action == "list":
        return list_config(cfg_file, as_json=as_json)
    if action == "get":
        key = getattr(args, "key", "")
        return get_config(key, cfg_file, as_json=as_json)
    if action == "set":
        key = getattr(args, "key", "")
        value = getattr(args, "value", "")
        return set_config(key, value, cfg_file)
    if action == "unset":
        key = getattr(args, "key", "")
        return unset_config(key, cfg_file)

    print(f"Error: Unknown config action '{action}'", file=sys.stderr)
    return 1
