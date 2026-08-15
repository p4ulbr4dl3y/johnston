"""Backwards-compatible re-export of error formatting helpers.

Canonical location: ``core.domain.defaults.errors`` (pure domain string
helpers). Kept for backward compatibility — callers should import directly
from the domain module.
"""
from core.domain.defaults.errors import format_tool_error as format_tool_error

__all__ = ["format_tool_error"]
