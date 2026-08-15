"""Backward-compatible re-export for core.markdown_scanner.

Canonical implementation lives in ``core.infrastructure.runtime.markdown_scanner``.
"""

from core.infrastructure.runtime.markdown_scanner import (
    MarkdownDirs,
    MarkdownScannerCache,
    MarkdownScanResult,
    build_markdown_dirs,
)

__all__ = [
    "MarkdownDirs",
    "MarkdownScanResult",
    "MarkdownScannerCache",
    "build_markdown_dirs",
]
