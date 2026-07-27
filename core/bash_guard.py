"""Compatibility wrapper for the renamed shell guard module."""

from core.shell_guard import analyze_bash_command, analyze_shell_command

__all__ = ["analyze_bash_command", "analyze_shell_command"]
