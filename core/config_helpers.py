import os
from typing import Any, Dict

from core.platform_utils import atomic_write_json


def ensure_json_config(file_path: str, default_data: Dict[str, Any]) -> None:
    """Ensures parent directory exists and initializes JSON config file if absent."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path):
        atomic_write_json(file_path, default_data, indent=2)
