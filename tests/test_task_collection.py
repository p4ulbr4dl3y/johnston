"""Unit tests for core.infrastructure.runtime.task_collection."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.infrastructure.runtime.task_collection import collect_current_tasks


def _shell_task(kind: str, session_id: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, session_id=session_id)


def test_collect_filters_shell_tasks_and_children(make_app_mock):
    """Shell tasks filtered by kind+session, subagents via store.children."""
    app = make_app_mock(
        task_manager=[
            _shell_task("shell", "s1"),
            _shell_task("shell", "s2"),
            _shell_task("subagent", "s1"),
        ],
        sm=MagicMock(),
    )
    children = [SimpleNamespace(id="sub-1")]
    app.sm.children.return_value = children

    tasks = collect_current_tasks(app, "s1")

    assert tasks.shell_tasks == [_shell_task("shell", "s1")]
    app.sm.children.assert_called_once_with("s1")
    assert tasks.subagent_tasks == children


def test_collect_missing_task_manager_yields_no_tasks(make_app_mock):
    """No task_manager -> bg_tasks stays empty, children still resolved."""
    app = make_app_mock(task_manager=None, sm=MagicMock())
    app.sm.children.return_value = []

    tasks = collect_current_tasks(app, "s1")

    assert tasks.shell_tasks == []
    app.sm.children.assert_called_once_with("s1")


def test_collect_null_app_falls_back_to_session_store():
    """app None -> no bg tasks, store resolved via SessionStore singleton."""
    store = MagicMock()
    store.list.return_value = []
    with patch("core.infrastructure.storage.session_store.SessionStore.get_instance", return_value=store):
        tasks = collect_current_tasks(None, "")

    assert tasks.shell_tasks == []
    store.list.assert_called_once_with(kind="subagent")
    assert tasks.subagent_tasks == []


def test_collect_empty_session_returns_all_and_lists_subagents(make_app_mock):
    """Empty session_id -> all shell tasks, subagents via store.list."""
    app = make_app_mock(
        task_manager=[_shell_task("shell", "s1"), _shell_task("shell", "s2")],
        sm=MagicMock(),
    )
    app.sm.list.return_value = []

    tasks = collect_current_tasks(app, "")

    assert tasks.shell_tasks == [_shell_task("shell", "s1"), _shell_task("shell", "s2")]
    app.sm.list.assert_called_once_with(kind="subagent")
    assert tasks.subagent_tasks == []


def test_collect_missing_store_falls_back_to_session_store(make_app_mock):
    """app.sm None -> SessionStore singleton used for children."""
    app = make_app_mock(task_manager=[_shell_task("shell", "s1")], sm=None)
    store = MagicMock()
    store.children.return_value = []
    with patch("core.infrastructure.storage.session_store.SessionStore.get_instance", return_value=store):
        tasks = collect_current_tasks(app, "s1")

    assert tasks.shell_tasks == [_shell_task("shell", "s1")]
    store.children.assert_called_once_with("s1")
    assert tasks.subagent_tasks == []
