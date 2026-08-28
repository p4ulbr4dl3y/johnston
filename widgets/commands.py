"""Slash commands for Johnston chat interface.

Decomposed into `widgets.presentation.commands`:
- Base: `BaseCommand`
- Helpers: `cancel_active_workers_and_tasks`, `cancel_active_workers`, `reset_app_state`
- Session commands: `NewCommand`, `ResumeCommand`, `CompactCommand`, `RewindCommand`, `ForkCommand`, `RenameCommand`, `DiffCommand`
- Provider commands: `ProvidersCommand`, `ModelsCommand`, `ThinkingEffortCommand`
- Tool commands: `SkillsCommand`, `MCPCommand`, `SubagentsCommand`, `ShellTasksCommand`, `QuestionsCommand`, `SandboxCommand`
- UI commands: `HelpCommand`, `CopyCommand`, `ThemeCommand`
"""
from __future__ import annotations

# Re-export provider actions for compatibility with mock patches
from core.application.provider.actions import (
    fetch_grouped_models,
    get_current_thinking_effort,
    select_model,
    set_provider_credentials,
    set_thinking_effort,
)

# Re-export session actions for compatibility with mock patches
from core.application.session.actions import (
    compact_session,
    get_rewind_git_stats,
    get_session_diff,
    new_session,
    rewind_session,
)
from core.application.skills.manager import get_skill_manager
from core.infrastructure.mcp import get_mcp_manager
from widgets.presentation.commands import (
    COMMAND_CLASSES,
    BaseCommand,
    CompactCommand,
    CopyCommand,
    DiffCommand,
    ForkCommand,
    HelpCommand,
    MCPCommand,
    ModelsCommand,
    NewCommand,
    ProvidersCommand,
    QuestionsCommand,
    RenameCommand,
    ResumeCommand,
    RewindCommand,
    SandboxCommand,
    ShellTasksCommand,
    SkillsCommand,
    SubagentsCommand,
    ThemeCommand,
    ThinkingEffortCommand,
    cancel_active_workers,
    cancel_active_workers_and_tasks,
    reset_app_state,
)

__all__ = [
    "BaseCommand",
    "COMMAND_CLASSES",
    "cancel_active_workers",
    "cancel_active_workers_and_tasks",
    "reset_app_state",
    "ModelsCommand",
    "ThinkingEffortCommand",
    "ProvidersCommand",
    "NewCommand",
    "ResumeCommand",
    "CompactCommand",
    "RewindCommand",
    "ForkCommand",
    "RenameCommand",
    "SkillsCommand",
    "MCPCommand",
    "SubagentsCommand",
    "ShellTasksCommand",
    "DiffCommand",
    "QuestionsCommand",
    "SandboxCommand",
    "CopyCommand",
    "ThemeCommand",
    "HelpCommand",
    "compact_session",
    "fetch_grouped_models",
    "get_current_thinking_effort",
    "get_mcp_manager",
    "get_rewind_git_stats",
    "get_session_diff",
    "get_skill_manager",
    "new_session",
    "rewind_session",
    "select_model",
    "set_provider_credentials",
    "set_thinking_effort",
]
