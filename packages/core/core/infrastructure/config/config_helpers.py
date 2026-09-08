import os
from typing import Any, Dict, Optional

from core.infrastructure.platform.platform_utils import atomic_write_json


def ensure_json_config(file_path: str, default_data: Dict[str, Any]) -> None:
    """Ensures parent directory exists and initializes JSON config file if absent."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path):
        atomic_write_json(file_path, default_data, indent=2)


def load_sandbox_config(config_file: Optional[str] = None) -> bool:
    """Load sandbox_enabled boolean from global config (~/.johnston/config.json)."""
    from core.infrastructure.config.settings import get_settings
    return get_settings(config_file).sandbox.enabled


def save_sandbox_config(enabled: bool, config_file: Optional[str] = None) -> None:
    """Save sandbox_enabled boolean to global config (~/.johnston/config.json)."""
    from core.infrastructure.config.settings import SandboxSettings, patch_settings
    patch_settings(config_file=config_file, sandbox=SandboxSettings(enabled=bool(enabled)))


def load_theme_config(config_file: Optional[str] = None) -> Optional[str]:
    """Load persisted theme name from global config (~/.johnston/config.json)."""
    from core.infrastructure.config.settings import get_settings
    return get_settings(config_file).theme


def save_theme_config(theme_name: str, config_file: Optional[str] = None) -> None:
    """Save active theme name to global config (~/.johnston/config.json)."""
    from core.infrastructure.config.settings import patch_settings
    val = str(theme_name).strip() if theme_name else None
    patch_settings(config_file=config_file, theme=val)



