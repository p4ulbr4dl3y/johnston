"""Centralized secret storage and resolution for LLM providers and MCP servers.

Secrets are stored in ~/.johnston/secrets.json and merged with os.environ.
The file is blocked from agent access in sandbox mode.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict

from core.infrastructure.platform.paths import CONFIG_DIR, SECRETS_FILE
from core.infrastructure.platform.platform_utils import read_json, update_json_config

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)\}|\$([A-Za-z0-9_]+)")


def load_secrets() -> Dict[str, str]:
    """Load secrets dictionary from ~/.johnston/secrets.json."""
    if not os.path.exists(SECRETS_FILE):
        return {}
    data = read_json(SECRETS_FILE, {})
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items() if v is not None}
    return {}


def save_secret(key: str, value: str) -> None:
    """Save or update a secret in ~/.johnston/secrets.json."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    update_json_config(SECRETS_FILE, lambda data: data.__setitem__(key, value), indent=2)


def get_secret(key: str, default: str = "") -> str:
    """Resolve secret by key from secrets.json first (user file override), then os.environ.

    Supports exact match, upper_snake_case, and <KEY>_API_KEY variants.
    """
    canonical = (key or "").strip()
    if not canonical:
        return default

    secrets = load_secrets()

    # 1. Exact match in secrets.json
    if canonical in secrets and str(secrets[canonical]).strip():
        return str(secrets[canonical]).strip()

    # 2. Exact match in os.environ
    if canonical in os.environ and os.environ[canonical].strip():
        return os.environ[canonical].strip()

    # 3. Uppercase normalized variants (e.g. "openrouter" -> "OPENROUTER", "OPENROUTER_API_KEY")
    upper_key = canonical.upper().replace("-", "_")
    for variant in (f"{upper_key}_API_KEY", upper_key, f"{upper_key}_TOKEN"):
        if variant in secrets and str(secrets[variant]).strip():
            return str(secrets[variant]).strip()
        if variant in os.environ and os.environ[variant].strip():
            return os.environ[variant].strip()

    return default


def interpolate_secrets(text: str) -> str:
    """Expand ${VAR_NAME} or $VAR_NAME placeholders from secrets and environment."""
    if not text or not isinstance(text, str):
        return text

    def _replace(match: re.Match) -> str:
        var_name = match.group(1) or match.group(2)
        val = get_secret(var_name)
        return val if val else match.group(0)

    return _ENV_VAR_PATTERN.sub(_replace, text)


def interpolate_secrets_in_obj(obj: Any) -> Any:
    """Recursively interpolate secrets in dicts, lists, and strings."""
    if isinstance(obj, str):
        return interpolate_secrets(obj)
    if isinstance(obj, dict):
        return {k: interpolate_secrets_in_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [interpolate_secrets_in_obj(item) for item in obj]
    return obj
