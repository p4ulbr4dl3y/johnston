import os

from core.platform_utils import johnston_config_dir

CONFIG_DIR = str(johnston_config_dir())
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROVIDERS_JSON_FILE = os.path.join(CONFIG_DIR, "providers.json")

SUBAGENTS_DIR = os.path.join(CONFIG_DIR, "subagents")
SUBAGENT_DEFS_DIR = os.path.join(SUBAGENTS_DIR, "definitions")
SUBAGENT_SESSIONS_DIR = os.path.join(SUBAGENTS_DIR, "sessions")

LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
LAST_TOOL_LOG_FILE = os.path.join(LOGS_DIR, "last_tool.log")
TEMP_IMAGES_DIR = os.path.join(CONFIG_DIR, "temp_images")

# Agent Execution Limits & Timeouts
DEFAULT_CONTEXT_LIMIT = 128000
CONTEXT_COMPACTION_THRESHOLD_RATIO = 0.75
MAX_CONCURRENT_SUBAGENTS = 5

# Theme Palette Constants (Monochrome Slate)
THEME_PRIMARY = "#ffffff"
THEME_SECONDARY = "#f4f4f5"
THEME_MUTED = "#71717a"
THEME_SUBTLE = "#e4e4e7"

# Standard Ignored Directories
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".johnston",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
}

