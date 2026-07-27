import os

from core.platform_utils import johnston_config_dir

CONFIG_DIR = str(johnston_config_dir())
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_DIR = os.path.join(CONFIG_DIR, "projects")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROVIDERS_JSON_FILE = os.path.join(CONFIG_DIR, "providers.json")

SUBAGENTS_DIR = os.path.join(CONFIG_DIR, "subagents")
SUBAGENT_DEFS_DIR = os.path.join(SUBAGENTS_DIR, "definitions")
SUBAGENT_SESSIONS_DIR = os.path.join(SUBAGENTS_DIR, "sessions")

LOGS_DIR = os.path.join(CONFIG_DIR, "logs")
TEMP_IMAGES_DIR = os.path.join(CONFIG_DIR, "temp_images")
LAST_TOOL_LOG_FILE = os.path.join(LOGS_DIR, "last_tool.log")
AUDIT_LOG_FILE = os.path.join(CONFIG_DIR, "audit.jsonl")

# Agent Execution Limits & Timeouts
DEFAULT_CONTEXT_LIMIT = 128000
CONTEXT_COMPACTION_THRESHOLD_RATIO = 0.75
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MAX_STEPS = 50
DEFAULT_MAX_TOOL_CALLS = 200
DEFAULT_MAX_WALL_SECONDS = 1800
DEFAULT_CHUNK_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
MAX_CONCURRENT_SUBAGENTS = 5
MAX_FETCH_RESPONSE_SIZE = 10 * 1024 * 1024

# Theme Palette Constants (Monochrome Slate)
THEME_BG = "#09090b"
THEME_CARD = "#18181b"
THEME_BORDER = "#27272a"
THEME_PRIMARY = "#ffffff"
THEME_SECONDARY = "#f4f4f5"
THEME_MUTED = "#71717a"
THEME_SUBTLE = "#e4e4e7"
