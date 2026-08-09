import os

from core.platform_utils import IMAGE_EXTENSIONS, johnston_config_dir  # noqa: F401  (IMAGE_EXTENSIONS re-exported)

CONFIG_DIR = str(johnston_config_dir())
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROVIDERS_JSON_FILE = os.path.join(CONFIG_DIR, "providers.json")

SUBAGENT_SESSIONS_DIR = os.path.join(CONFIG_DIR, "subagents", "sessions")
SUBAGENT_LOGS_DIR = os.path.join(CONFIG_DIR, "subagents", "logs")

LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
LAST_TOOL_LOG_FILE = os.path.join(LOGS_DIR, "last_tool.log")
TEMP_IMAGES_DIR = os.path.join(CONFIG_DIR, "temp_images")
WORKTREES_DIR = os.path.join(CONFIG_DIR, "worktrees")
PROMPT_HISTORY_FILE = os.path.join(CONFIG_DIR, "prompt_history.json")

# Permissions Defaults (path to project-level permissions file)
PROJECT_PERMISSIONS_FILE = ".johnston/permissions.json"
