"""Path constants for the Johnston application."""
import os

from core.infrastructure.platform.platform_utils import IMAGE_EXTENSIONS, johnston_config_dir

__all__ = [
    "IMAGE_EXTENSIONS",
    "CONFIG_DIR",
    "PROJECTS_DIR",
    "CONFIG_FILE",
    "SECRETS_FILE",
    "PROVIDERS_JSON_FILE",
    "CACHE_DIR",
    "LOGS_DIR",
    "TEMP_IMAGES_DIR",
    "WORKTREES_DIR",
    "SHADOW_REPOS_DIR",
    "PROMPT_HISTORY_FILE",
    "THEMES_DIR",
]

CONFIG_DIR = str(johnston_config_dir())
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
SECRETS_FILE = os.path.join(CONFIG_DIR, "secrets.json")
PROVIDERS_JSON_FILE = os.path.join(CONFIG_DIR, "providers.json")
CACHE_DIR = os.path.join(CONFIG_DIR, "cache")
THEMES_DIR = os.path.join(CONFIG_DIR, "themes")

LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
TEMP_IMAGES_DIR = os.path.join(CONFIG_DIR, "temp_images")
WORKTREES_DIR = os.path.join(CONFIG_DIR, "worktrees")
SHADOW_REPOS_DIR = os.path.join(CONFIG_DIR, "shadow_repos")
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
