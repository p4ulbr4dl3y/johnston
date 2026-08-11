import os

from core.platform_utils import IMAGE_EXTENSIONS, johnston_config_dir  # noqa: F401  (IMAGE_EXTENSIONS re-exported)

CONFIG_DIR = str(johnston_config_dir())
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROVIDERS_JSON_FILE = os.path.join(CONFIG_DIR, "providers.json")

LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
TEMP_IMAGES_DIR = os.path.join(CONFIG_DIR, "temp_images")
WORKTREES_DIR = os.path.join(CONFIG_DIR, "worktrees")
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")
