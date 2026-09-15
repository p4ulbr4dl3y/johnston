"""OS clipboard integration utilities for the Johnston TUI."""
from __future__ import annotations

from typing import Any

__all__ = [
    "copy_to_os_clipboard_async",
    "get_clipboard_image_or_file",
]


def copy_to_os_clipboard_async(text: str) -> Any:
    """Copy text to the OS clipboard asynchronously."""
    from johnston.core.infrastructure.platform.platform_utils import (
        copy_to_os_clipboard_async as _f,
    )

    return _f(text)


def get_clipboard_image_or_file(*args: Any, **kwargs: Any) -> Any:
    """Return image/file from the OS clipboard."""
    from johnston.core.infrastructure.platform.platform_utils import (
        get_clipboard_image_or_file as _f,
    )

    return _f(*args, **kwargs)
