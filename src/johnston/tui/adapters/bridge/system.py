"""System, platform, configuration, and runtime bridge adapters."""
from __future__ import annotations

import asyncio
from typing import Any

from johnston.core.infrastructure.platform.paths import (
    IMAGE_EXTENSIONS,
    TEMP_IMAGES_DIR,
    THEMES_DIR,
    WORKTREES_DIR,
)
from johnston.core.infrastructure.runtime.lru import LruCache

__all__ = [
    "IMAGE_EXTENSIONS",
    "LruCache",
    "TEMP_IMAGES_DIR",
    "THEMES_DIR",
    "WORKTREES_DIR",
    "aclose_tools",
    "adopt_task_exception",
    "atomic_write_json",
    "close_tools",
    "compute_adaptive_palette",
    "copy_to_os_clipboard_async",
    "format_background_notification",
    "get_clipboard_image_or_file",
    "get_config_paths",
    "get_settings",
    "get_theme_by_name",
    "get_theme_class",
    "get_theme_constants",
    "get_theme_variable_defaults",
    "get_theme_vars",
    "get_workspace_root",
    "install_asyncio_exception_handler",
    "is_ansi_theme",
    "is_builtin_tool",
    "is_windows",
    "list_themes",
    "load_sandbox_config",
    "load_theme_config",
    "normalize_tool_name",
    "query_terminal_palette",
    "read_json",
    "save_sandbox_config",
    "save_theme_config",
    "truncate_output",
]


def get_workspace_root() -> str:
    """Current workspace root path from core."""
    from johnston.core.infrastructure.platform import paths

    return paths.workspace_root()


def get_config_paths() -> Any:
    """Core platform path constants (CONFIG_DIR, PROMPT_HISTORY_FILE, ...)."""
    from johnston.core.infrastructure.platform import paths as _paths

    return _paths


def install_asyncio_exception_handler() -> None:
    """Install the global asyncio exception handler."""
    from johnston.core.infrastructure.platform.logging_setup import (
        install_asyncio_exception_handler as _f,
    )

    _f()


def adopt_task_exception(task: Any) -> None:
    """Attach an exception handler to a tracked task."""
    from johnston.core.infrastructure.platform.logging_setup import (
        adopt_task_exception as _f,
    )

    _f(task)


def is_windows() -> bool:
    """True on Windows platform (core platform helper)."""
    from johnston.core.client import is_windows as _f

    return _f()


def copy_to_os_clipboard_async(text: str) -> Any:
    """Copy text to the OS clipboard (async helper from core platform utils)."""
    from johnston.core.infrastructure.platform.platform_utils import (
        copy_to_os_clipboard_async as _f,
    )

    return _f(text)


def get_clipboard_image_or_file(*args: Any, **kwargs: Any) -> Any:
    """Return image/file from the OS clipboard (core platform helper)."""
    from johnston.core.infrastructure.platform.platform_utils import (
        get_clipboard_image_or_file as _f,
    )

    return _f(*args, **kwargs)


def query_terminal_palette(*args: Any, **kwargs: Any) -> Any:
    """Query the terminal color palette (core platform helper)."""
    from johnston.core.infrastructure.platform.terminal_theme import (
        query_terminal_palette as _f,
    )

    return _f(*args, **kwargs)


def compute_adaptive_palette(bg: str | None = None, fg: str | None = None) -> Any:
    """Compute an adapted terminal palette (core platform helper)."""
    from johnston.core.infrastructure.platform.terminal_theme import (
        compute_adaptive_palette as _f,
    )

    return _f(bg, fg)


def get_theme_variable_defaults() -> dict[str, str]:
    """Return design-token defaults from the default theme."""
    from johnston.core.domain.defaults.themes import ZINC_DARK

    return dict(ZINC_DARK.tcss_vars)


def load_theme_config() -> Any:
    """Load the active theme config (core config helper)."""
    from johnston.core.infrastructure.config.config_helpers import (
        load_theme_config as _f,
    )

    return _f()


def save_theme_config(theme_name: str) -> None:
    """Persist the active theme config (core config helper)."""
    from johnston.core.infrastructure.config.config_helpers import (
        save_theme_config as _f,
    )

    _f(theme_name)


def get_theme_constants() -> dict[str, Any]:
    """Theme/status color constants from core domain defaults."""
    from johnston.core.domain.defaults.config import (
        COLOR_DIFF_ADD_BG,
        COLOR_DIFF_ADD_FG,
        COLOR_DIFF_GUTTER,
        COLOR_DIFF_REMOVE_BG,
        COLOR_DIFF_REMOVE_FG,
        COLOR_STATUS_ERROR,
        COLOR_STATUS_RUNNING,
        COLOR_STATUS_SUCCESS,
        THEME_MUTED,
        THEME_PRIMARY,
        THEME_SECONDARY,
        THEME_SUBTLE,
    )

    return dict(
        COLOR_DIFF_ADD_BG=COLOR_DIFF_ADD_BG,
        COLOR_DIFF_ADD_FG=COLOR_DIFF_ADD_FG,
        COLOR_DIFF_GUTTER=COLOR_DIFF_GUTTER,
        COLOR_DIFF_REMOVE_BG=COLOR_DIFF_REMOVE_BG,
        COLOR_DIFF_REMOVE_FG=COLOR_DIFF_REMOVE_FG,
        COLOR_STATUS_ERROR=COLOR_STATUS_ERROR,
        COLOR_STATUS_RUNNING=COLOR_STATUS_RUNNING,
        COLOR_STATUS_SUCCESS=COLOR_STATUS_SUCCESS,
        THEME_MUTED=THEME_MUTED,
        THEME_PRIMARY=THEME_PRIMARY,
        THEME_SECONDARY=THEME_SECONDARY,
        THEME_SUBTLE=THEME_SUBTLE,
    )


def get_theme_vars() -> Any:
    """Design tokens used by the markdown/theme layer (core defaults)."""
    from johnston.core.domain.defaults.themes import ZINC_DARK as _f

    return _f


def list_themes() -> Any:
    """List available themes (core defaults, live lookup)."""
    import johnston.core.domain.defaults.themes as _m

    return _m.list_themes()


def get_theme_by_name(name: str) -> Any:
    """Resolve a theme by name (core defaults, live lookup)."""
    import johnston.core.domain.defaults.themes as _m

    return _m.get_theme(name)


def is_ansi_theme(theme: Any) -> bool:
    """Whether a theme is ANSI-based (core entity helper)."""
    from johnston.core.domain.entities.theme import is_ansi_theme as _f

    return _f(theme)


def get_theme_class() -> Any:
    """Core Theme entity class."""
    from johnston.core.domain.entities.theme import Theme as _f

    return _f


def read_json(path: str, default: Any = None) -> Any:
    """Read a JSON file (core platform helper)."""
    from johnston.core.infrastructure.platform.platform_utils import read_json as _f

    return _f(path, default=default)


def atomic_write_json(path: str, data: Any, indent: int = 2) -> None:
    """Atomically write a JSON file (core platform helper)."""
    from johnston.core.infrastructure.platform.platform_utils import (
        atomic_write_json as _f,
    )

    _f(path, data, indent=indent)


def get_settings() -> Any:
    """Read app settings (core config)."""
    from johnston.core.infrastructure.config.settings import get_settings as _gs

    return _gs()


def load_sandbox_config() -> bool:
    """Load the sandbox default from core config."""
    from johnston.core.infrastructure.config.config_helpers import (
        load_sandbox_config as _f,
    )

    return _f()


def save_sandbox_config(enabled: bool) -> None:
    """Persist the sandbox default (core config helper, live lookup)."""
    import johnston.core.infrastructure.config.config_helpers as _m

    _m.save_sandbox_config(enabled)


def normalize_tool_name(name: str) -> str:
    """Normalize tool name for display and lookup."""
    from johnston.core.infrastructure.runtime.tool_name import (
        normalize_tool_name as _f,
    )

    return _f(name)


def close_tools() -> None:
    """Close all registered tool instances (used on app shutdown)."""
    from johnston.core.tools.registry import aclose_tools as _aclose_tools

    asyncio.run(_aclose_tools())


def aclose_tools() -> Any:
    """Core tool registry async close (live lookup)."""
    from johnston.core.tools.registry import aclose_tools as _f

    return _f()


def truncate_output(*args: Any, **kwargs: Any) -> Any:
    """Truncate tool output for display (core tools base, live lookup)."""
    from johnston.core.tools.base import truncate_output as _f

    return _f(*args, **kwargs)


def format_background_notification(*args: Any, **kwargs: Any) -> Any:
    """Format a background-task completion notification (core tools base)."""
    from johnston.core.tools.base import format_background_notification as _f

    return _f(*args, **kwargs)


def is_builtin_tool(name: str) -> bool:
    """Whether a tool name is registered in the core tool registry."""
    from johnston.core.tools.registry import REGISTRY as _r

    return name in _r
