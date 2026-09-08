"""Role configuration for subagents, decomposed into pure, testable steps.

Provides role resolution + fallback, provider switching, tool filtering with
hardened descriptions, and system-prompt/model wiring.
"""

from johnston_core.role_registry import get_role_display_name
from johnston_core.roles.apply import apply_role
from johnston_core.roles.prompt import apply_prompt, format_role_prompt
from johnston_core.roles.provider import apply_provider, rebind_provider
from johnston_core.roles.resolve import resolve_role
from johnston_core.roles.tools import apply_role_tools

__all__ = [
    "apply_prompt",
    "apply_provider",
    "apply_role",
    "apply_role_tools",
    "format_role_prompt",
    "get_role_display_name",
    "rebind_provider",
    "resolve_role",
]

