"""Shared permission helpers and constants, breaking cycles between config and manager."""
import os
import sys
from typing import Optional

from johnston.core.infrastructure.platform.paths import CONFIG_FILE, LOGS_DIR, SECRETS_FILE
from johnston.core.infrastructure.runtime.git_utils import is_git_repository

__all__ = [
    "CONFIG_FILE",
    "LOGS_DIR",
    "SECRETS_FILE",
    "is_git_repository",
    "get_global_config_file",
    "check_is_git_repository",
    "is_strict_ancestor",
]


def is_strict_ancestor(ancestor: str, target: str) -> bool:
    """True when ``target`` is a strict parent directory of ``ancestor``."""
    if ancestor == target:
        return False
    try:
        return os.path.commonpath([ancestor, target]) == target
    except ValueError:
        return False


def get_global_config_file() -> str:
    """Resolve active CONFIG_FILE dynamically respecting any test mocks on permission_manager."""
    pm_mod = sys.modules.get("johnston.core.application.permission.permission_manager")
    if pm_mod is not None and hasattr(pm_mod, "CONFIG_FILE"):
        return pm_mod.CONFIG_FILE
    return CONFIG_FILE


def check_is_git_repository(pdir: Optional[str] = None) -> bool:
    """Resolve is_git_repository dynamically respecting any test mocks on permission_manager."""
    pm_mod = sys.modules.get("johnston.core.application.permission.permission_manager")
    if pm_mod is not None and hasattr(pm_mod, "is_git_repository"):
        try:
            return pm_mod.is_git_repository(pdir)
        except Exception:
            return False
    return is_git_repository(pdir)
