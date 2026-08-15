"""Backwards-compatible re-export. Canonical location: core.infrastructure.platform.paths"""
from core.infrastructure.platform.paths import (  # noqa: F401
    CONFIG_DIR,
    CONFIG_FILE,
    IMAGE_EXTENSIONS,
    LOGS_DIR,
    PROJECTS_DIR,
    PROMPT_HISTORY_FILE,
    PROVIDERS_JSON_FILE,
    TEMP_IMAGES_DIR,
    WORKTREES_DIR,
)

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
