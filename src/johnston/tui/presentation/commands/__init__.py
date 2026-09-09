"""Slash commands for Johnston chat interface."""
from __future__ import annotations

from johnston.tui.presentation.commands.base import BaseCommand
from johnston.tui.presentation.commands.branch_command import BranchCommand
from johnston.tui.presentation.commands.helpers import (
    cancel_active_workers,
    cancel_active_workers_and_tasks,
    reset_app_state,
)
from johnston.tui.presentation.commands.provider_commands import (
    ModelsCommand,
    ProvidersCommand,
    ThinkingEffortCommand,
)
from johnston.tui.presentation.commands.session_commands import (
    CompactCommand,
    DiffCommand,
    ForkCommand,
    NewCommand,
    RenameCommand,
    ResumeCommand,
    RewindCommand,
)
from johnston.tui.presentation.commands.tool_commands import (
    MCPCommand,
    QuestionsCommand,
    SandboxCommand,
    ShellTasksCommand,
    SkillsCommand,
    SubagentsCommand,
)
from johnston.tui.presentation.commands.ui_commands import (
    CommandsCommand,
    CopyCommand,
    HelpCommand,
    KeybindsCommand,
    ThemeCommand,
)
from johnston.tui.presentation.commands.workspace_command import WorkspaceCommand

COMMAND_CLASSES = [
    ModelsCommand,
    ThinkingEffortCommand,
    ProvidersCommand,
    WorkspaceCommand,
    BranchCommand,
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
    CommandsCommand,
    KeybindsCommand,
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
    "WorkspaceCommand",
    "BranchCommand",
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
    "CommandsCommand",
    "KeybindsCommand",
]
