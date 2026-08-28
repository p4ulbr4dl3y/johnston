import os
from typing import Any, Dict, Optional

from core.infrastructure.platform import paths
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json


def ensure_json_config(file_path: str, default_data: Dict[str, Any]) -> None:
    """Ensures parent directory exists and initializes JSON config file if absent."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path):
        atomic_write_json(file_path, default_data, indent=2)


def load_sandbox_config(config_file: Optional[str] = None) -> bool:
    """Load sandbox_enabled boolean from global config (~/.johnston/config.json)."""
    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if isinstance(data, dict):
            val = data.get("sandbox_enabled", False)
            if isinstance(val, bool):
                return val
    except Exception:
        pass
    return False


def save_sandbox_config(enabled: bool, config_file: Optional[str] = None) -> None:
    """Save sandbox_enabled boolean to global config (~/.johnston/config.json)."""
    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if not isinstance(data, dict):
            data = {}
        data["sandbox_enabled"] = bool(enabled)
        atomic_write_json(config_file, data, indent=2)
    except Exception:
        pass


def load_theme_config(config_file: Optional[str] = None) -> Optional[str]:
    """Load persisted theme name from global config (~/.johnston/config.json)."""
    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if isinstance(data, dict):
            val = data.get("theme")
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    return None


def save_theme_config(theme_name: str, config_file: Optional[str] = None) -> None:
    """Save active theme name to global config (~/.johnston/config.json)."""
    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if not isinstance(data, dict):
            data = {}
        data["theme"] = str(theme_name).strip()
        atomic_write_json(config_file, data, indent=2)
    except Exception:
        pass


def load_max_concurrent_subagents(config_file: Optional[str] = None) -> int:
    """Load max_concurrent_subagents from env var or global config (~/.johnston/config.json)."""
    from core.domain.defaults.config import MAX_CONCURRENT_SUBAGENTS

    env_val = os.getenv("JOHNSTON_MAX_CONCURRENT_SUBAGENTS")
    if env_val:
        try:
            parsed = int(env_val.strip())
            if parsed > 0:
                return parsed
        except ValueError:
            pass

    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if isinstance(data, dict):
            val = data.get("max_concurrent_subagents")
            if isinstance(val, int) and val > 0:
                return val
    except Exception:
        pass
    return MAX_CONCURRENT_SUBAGENTS


def save_max_concurrent_subagents(limit: int, config_file: Optional[str] = None) -> None:
    """Save max_concurrent_subagents to global config (~/.johnston/config.json)."""
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("max_concurrent_subagents must be a positive integer")
    config_file = config_file or paths.CONFIG_FILE
    try:
        data = read_json(config_file, default={})
        if not isinstance(data, dict):
            data = {}
        data["max_concurrent_subagents"] = limit
        atomic_write_json(config_file, data, indent=2)
    except Exception:
        pass

