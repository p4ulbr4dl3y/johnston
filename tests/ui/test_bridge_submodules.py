"""Tests for modularized bridge submodules and core_bridge facade."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from johnston.tui.adapters import core_bridge
from johnston.tui.adapters.bridge import (
    client as bridge_client,
)
from johnston.tui.adapters.bridge import (
    git as bridge_git,
)
from johnston.tui.adapters.bridge import (
    session as bridge_session,
)
from johnston.tui.adapters.bridge import (
    system as bridge_system,
)
from johnston.tui.adapters.bridge import (
    tasks as bridge_tasks,
)


def test_core_bridge_reexports_all_submodule_symbols():
    """Verify that core_bridge re-exports all symbols from the bridge submodules."""
    for module in (bridge_client, bridge_git, bridge_system, bridge_tasks, bridge_session):
        for symbol_name in module.__all__:
            assert hasattr(core_bridge, symbol_name), f"Missing symbol in core_bridge: {symbol_name}"
            assert getattr(core_bridge, symbol_name) is getattr(module, symbol_name)


def test_bridge_client_exports():
    """Verify bridge/client.py exports expected symbols."""
    assert hasattr(bridge_client, "JohnstonClient")
    assert hasattr(bridge_client, "ProviderReadyState")
    assert hasattr(bridge_client, "ensure_provider_ready")
    assert hasattr(bridge_client, "build_core_services")
    assert hasattr(bridge_client, "configure_agent")
    assert hasattr(bridge_client, "stream_step_to_session_event")
    assert hasattr(bridge_client, "sync_session_metrics")
    assert hasattr(bridge_client, "catalog")
    assert hasattr(bridge_client, "format_context_tokens")
    assert hasattr(bridge_client, "estimate_tokens")
    assert hasattr(bridge_client, "display_thinking_effort")
    assert hasattr(bridge_client, "get_effort_auto")
    assert bridge_client.get_effort_auto() is not None


def test_bridge_git_exports():
    """Verify bridge/git.py exports expected symbols."""
    assert hasattr(bridge_git, "get_branch_info")
    assert hasattr(bridge_git, "get_diff_stats")
    assert hasattr(bridge_git, "make_git_diff")
    assert hasattr(bridge_git, "GitWorktreeManager")
    assert hasattr(bridge_git, "get_git_worktree_manager")
    assert hasattr(bridge_git, "get_ignore_dirs")
    assert hasattr(bridge_git, "worktrees_dir")
    assert hasattr(bridge_git, "WORKTREES_DIR")

    diff = bridge_git.make_git_diff("foo\n", "bar\n")
    assert "-foo" in diff
    assert "+bar" in diff


def test_bridge_system_exports():
    """Verify bridge/system.py exports expected symbols."""
    assert hasattr(bridge_system, "get_workspace_root")
    assert hasattr(bridge_system, "get_config_paths")
    assert hasattr(bridge_system, "install_asyncio_exception_handler")
    assert hasattr(bridge_system, "adopt_task_exception")
    assert hasattr(bridge_system, "is_windows")
    assert hasattr(bridge_system, "copy_to_os_clipboard_async")
    assert hasattr(bridge_system, "query_terminal_palette")
    assert hasattr(bridge_system, "compute_adaptive_palette")
    assert hasattr(bridge_system, "read_json")
    assert hasattr(bridge_system, "atomic_write_json")
    assert hasattr(bridge_system, "IMAGE_EXTENSIONS")
    assert hasattr(bridge_system, "TEMP_IMAGES_DIR")
    assert hasattr(bridge_system, "THEMES_DIR")
    assert hasattr(bridge_system, "WORKTREES_DIR")
    assert hasattr(bridge_system, "LruCache")
    assert bridge_system.normalize_tool_name("test_tool") == "test_tool"


def test_bridge_tasks_exports():
    """Verify bridge/tasks.py exports expected symbols."""
    assert hasattr(bridge_tasks, "collect_current_tasks")
    assert hasattr(bridge_tasks, "collect_task_summary")
    assert hasattr(bridge_tasks, "filter_to_session")
    assert hasattr(bridge_tasks, "format_duration")
    assert hasattr(bridge_tasks, "kill_subagent")
    assert hasattr(bridge_tasks, "extract_task_status_details")
    assert hasattr(bridge_tasks, "get_extract_task_status_details")
    assert hasattr(bridge_tasks, "process_carriage_returns")
    assert hasattr(bridge_tasks, "is_spinner_line")
    assert hasattr(bridge_tasks, "strip_ansi")

    assert bridge_tasks.format_duration(65) == "1m 05s"
    assert bridge_tasks.strip_ansi("\033[31mred\033[0m") == "red"


def test_bridge_session_exports():
    """Verify bridge/session.py exports expected symbols."""
    assert hasattr(bridge_session, "get_session_actions")
    assert hasattr(bridge_session, "auto_title_session")
    assert hasattr(bridge_session, "clean_heuristic_title")
    assert hasattr(bridge_session, "is_ui_visible_user_message")
    assert hasattr(bridge_session, "get_fork_base_max_len")
    assert hasattr(bridge_session, "cycle_execution_mode")
    assert hasattr(bridge_session, "apply_permission_choice")
    assert hasattr(bridge_session, "get_skill_helpers")
    assert hasattr(bridge_session, "get_skill_manager")
    assert hasattr(bridge_session, "list_skills")
    assert hasattr(bridge_session, "get_store")

    assert bridge_session.clean_heuristic_title("hello  world") == "hello world"
    assert bridge_session.get_fork_base_max_len() > 0


def test_ensure_provider_ready_mockable():
    """Verify ensure_provider_ready resolves dynamically from core engine."""
    with patch(
        "johnston.core.application.generation.engine.ensure_provider_ready",
        return_value="mock_state",
    ):
        result = bridge_client.ensure_provider_ready(MagicMock(), MagicMock())
        assert result == "mock_state"

        result_cb = core_bridge.ensure_provider_ready(MagicMock(), MagicMock())
        assert result_cb == "mock_state"
