"""DTOs consumed exclusively by TUI layer via core_bridge.

These are the rendering-state contracts between core and UI.  Screens,
widgets and mixins should import ONLY from this module (via
``tui.adapters.core_bridge``), never from domain/infrastructure directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Status footer
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class StatusFooterDTO:
    """Ready-to-render status bar state."""

    provider_key: str = "default"
    provider_display: str = ""
    is_connected: bool = False
    model_name: str = ""
    clean_model: str = ""
    agent_role: str = "worker"
    directory: str = ""
    active_bg_tasks: int = 0
    subagents_active: int = 0
    subagents_total: int = 0
    context_used: int = 0
    total_tokens: int = 0
    context_window: str = "128k"
    context_limit: int = 128000
    cost_usd: float = 0.0
    thinking_effort: str = ""
    skills_visible: int = 0
    skills_total: int = 0
    mcp_active: int = 0
    mcp_total: int = 0
    attachments_count: int = 0
    sandbox_enabled: bool = False
    execution_mode: str = "auto"


# ---------------------------------------------------------------------------
# Session snapshot
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class SessionSnapshotDTO:
    """Session state collected for persistence and display."""

    id: str = ""
    title: str = ""
    role: str = "worker"
    messages: list[Any] = field(default_factory=list)
    agent_history: list[Any] = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    last_context_tokens: int = 0
    tokens_cache_read: int = 0
    project_dir: str = ""
    branch_name: str = ""


# ---------------------------------------------------------------------------
# Role info
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class RoleInfoDTO:
    """Current role state for display and switching."""

    key: str = "worker"
    display_name: str = "Worker"
    available: list[str] = field(default_factory=list)
    display_names: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Footer cache (providers / skills / MCP)
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class FooterCacheDTO:
    """Aggregated footer-cache payload (providers, skills, MCP servers)."""

    providers: dict[str, Any] = field(default_factory=dict)
    skills_visible: int = 0
    skills_total: int = 0
    mcp_servers: list[Any] = field(default_factory=list)
