"""Role configuration for subagents, decomposed into pure, testable steps.

The old ``apply_subagent_role`` monolith in core/application/session/stream.py (housed previously at core/subagent_stream.py) combined
four unrelated concerns: role resolution + fallback, provider switching, tool
filtering with a hardened shell description, and system-prompt/model wiring.
This package splits that into small functions so each concern is independently
testable and the monolith can become a thin facade.
"""

from core.roles.apply import apply_role
from core.roles.prompt import apply_prompt
from core.roles.provider import apply_provider, rebind_provider
from core.roles.resolve import resolve_role
from core.roles.tools import apply_role_tools

__all__ = [
    "apply_prompt",
    "apply_provider",
    "apply_role",
    "apply_role_tools",
    "rebind_provider",
    "resolve_role",
]
