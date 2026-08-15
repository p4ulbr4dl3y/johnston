"""Path constants for the Johnston application."""
import os

from core.infrastructure.platform.platform_utils import IMAGE_EXTENSIONS, johnston_config_dir

__all__ = [
    "IMAGE_EXTENSIONS",
    "CONFIG_DIR",
    "PROJECTS_DIR",
    "CONFIG_FILE",
    "PROVIDERS_JSON_FILE",
    "LOGS_DIR",
    "TEMP_IMAGES_DIR",
    "WORKTREES_DIR",
    "PROMPT_HISTORY_FILE",
]

CONFIG_DIR = str(johnston_config_dir())
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROVIDERS_JSON_FILE = os.path.join(CONFIG_DIR, "providers.json")

LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
TEMP_IMAGES_DIR = os.path.join(CONFIG_DIR, "temp_images")
WORKTREES_DIR = os.path.join(CONFIG_DIR, "worktrees")
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
