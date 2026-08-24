import os
from typing import Any, Dict

from core.infrastructure.platform.paths import CONFIG_FILE
from core.infrastructure.platform.platform_utils import atomic_write_json, read_json


def ensure_json_config(file_path: str, default_data: Dict[str, Any]) -> None:
    """Ensures parent directory exists and initializes JSON config file if absent."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path):
        atomic_write_json(file_path, default_data, indent=2)


def load_sandbox_config(config_file: str = CONFIG_FILE) -> bool:
    """Load sandbox_enabled boolean from global config (~/.johnston/config.json)."""
    try:
        data = read_json(config_file, default={})
        if isinstance(data, dict):
            val = data.get("sandbox_enabled", False)
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, str)):
                return str(val).lower() in ("true", "1", "yes", "on")
    except Exception:
        pass
    return False


def save_sandbox_config(enabled: bool, config_file: str = CONFIG_FILE) -> None:
    """Save sandbox_enabled boolean to global config (~/.johnston/config.json)."""
    try:
        data = read_json(config_file, default={})
        if not isinstance(data, dict):
            data = {}
        data["sandbox_enabled"] = bool(enabled)
        atomic_write_json(config_file, data, indent=2)
    except Exception:
        pass
