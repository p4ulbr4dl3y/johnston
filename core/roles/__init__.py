"""Role configuration for subagents, decomposed into pure, testable steps.

Provides role resolution + fallback, provider switching, tool filtering with
hardened descriptions, and system-prompt/model wiring.
"""

from core.roles.apply import apply_role
from core.roles.prompt import apply_prompt, format_role_prompt
from core.roles.provider import apply_provider, rebind_provider
from core.roles.resolve import resolve_role
from core.roles.tools import apply_role_tools

__all__ = [
    "apply_prompt",
    "apply_provider",
    "apply_role",
    "apply_role_tools",
    "format_role_prompt",
    "rebind_provider",
    "resolve_role",
]

