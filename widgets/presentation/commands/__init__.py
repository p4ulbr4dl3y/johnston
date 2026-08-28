"""Slash commands for Johnston chat interface."""
from __future__ import annotations

from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.commands.helpers import (
    cancel_active_workers,
    cancel_active_workers_and_tasks,
    reset_app_state,
)
from widgets.presentation.commands.provider_commands import (
    ModelsCommand,
    ProvidersCommand,
    ThinkingEffortCommand,
)
from widgets.presentation.commands.session_commands import (
    CompactCommand,
    DiffCommand,
    ForkCommand,
    NewCommand,
    RenameCommand,
    ResumeCommand,
    RewindCommand,
)
from widgets.presentation.commands.tool_commands import (
    MCPCommand,
    QuestionsCommand,
    SandboxCommand,
    ShellTasksCommand,
    SkillsCommand,
    SubagentsCommand,
)
from widgets.presentation.commands.ui_commands import (
    CopyCommand,
    HelpCommand,
    ThemeCommand,
)

COMMAND_CLASSES = [
    ModelsCommand,
    ThinkingEffortCommand,
    ProvidersCommand,
    NewCommand,
    ResumeCommand,
    CompactCommand,
    RewindCommand,
    ForkCommand,
    RenameCommand,
    SkillsCommand,
    MCPCommand,
    SubagentsCommand,
    ShellTasksCommand,
    DiffCommand,
    QuestionsCommand,
    SandboxCommand,
    CopyCommand,
    ThemeCommand,
    HelpCommand,
]

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
]
