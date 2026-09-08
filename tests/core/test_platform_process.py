from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.policies.policy_shell import check_read_only_command_mutations
from core.infrastructure.platform.process import spawn_shell_process, spawn_windows_process
from tools.context import ToolContext


@pytest.mark.asyncio
async def test_spawn_shell_process_sandboxed():
    with (
        patch(
            "core.infrastructure.platform.sandbox.build_sandboxed_command",
            return_value=("/bin/sandbox", ["arg1", "arg2"], True),
        ),
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
    ):
        await spawn_shell_process(
            command="ls",
            env={"A": "1"},
            cwd="/tmp",
            workspace_dir="/tmp",
            sandbox_enabled=True,
        )
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        assert args[0] == "/bin/sandbox"
        assert args[1:] == ("arg1", "arg2")
        assert kwargs["cwd"] == "/tmp"


@pytest.mark.asyncio
async def test_spawn_shell_process_windows_spawner():
    mock_spawner = AsyncMock()
    await spawn_shell_process(
        command="dir",
        env={"A": "1"},
        cwd="/tmp",
        is_win=True,
        windows_spawner=mock_spawner,
    )
    mock_spawner.assert_called_once_with("dir", {"A": "1"}, cwd="/tmp")


@pytest.mark.asyncio
async def test_spawn_shell_process_windows_default():
    with (
        patch(
            "core.infrastructure.platform.process.spawn_windows_process",
            new_callable=AsyncMock,
        ) as mock_win,
    ):
        await spawn_shell_process(
            command="dir",
            env={"A": "1"},
            cwd="/tmp",
            is_win=True,
        )
        mock_win.assert_called_once_with("dir", {"A": "1"}, cwd="/tmp", executable=None)


@pytest.mark.asyncio
async def test_spawn_shell_process_posix():
    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
        await spawn_shell_process(
            command="echo hi",
            env={"A": "1"},
            cwd="/tmp",
            is_win=False,
            executable="/bin/zsh",
        )
        mock_shell.assert_called_once()
        args, kwargs = mock_shell.call_args
        assert args[0] == "echo hi"
        assert kwargs["executable"] == "/bin/zsh"
        assert kwargs["cwd"] == "/tmp"


@pytest.mark.asyncio
async def test_spawn_windows_process_powershell():
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        await spawn_windows_process(
            command="Get-ChildItem",
            env={"A": "1"},
            cwd="C:\\test",
            executable="powershell.exe",
        )
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        assert args[0] == "powershell.exe"
        assert "-NoProfile" in args
        assert "-Command" in args
        assert kwargs["cwd"] == "C:\\test"


@pytest.mark.asyncio
async def test_spawn_windows_process_cmd():
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        await spawn_windows_process(
            command="dir",
            env={"A": "1"},
            cwd="C:\\test",
            executable="cmd.exe",
        )
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        assert args[0] == "cmd.exe"
        assert "/c" in args
        assert "dir" in args
        assert kwargs["cwd"] == "C:\\test"


@pytest.mark.asyncio
async def test_spawn_windows_process_fallback():
    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
        await spawn_windows_process(
            command="echo 1",
            env={"A": "1"},
            cwd="C:\\test",
            executable=None,
        )
        mock_shell.assert_called_once()
        args, kwargs = mock_shell.call_args
        assert args[0] == "echo 1"
        assert kwargs["cwd"] == "C:\\test"


def test_check_read_only_command_mutations_policies():
    assert check_read_only_command_mutations("") is None
    assert check_read_only_command_mutations("git status") is None
    assert check_read_only_command_mutations("git log -n 5") is None
    assert check_read_only_command_mutations("git diff") is None
    assert "git commit is not permitted" in (check_read_only_command_mutations("git commit -m msg") or "")
    assert "git push is not permitted" in (check_read_only_command_mutations("git push origin main") or "")
    assert "git branch creation is not permitted" in (check_read_only_command_mutations("git branch feature") or "")
    assert "git tag creation is not permitted" in (check_read_only_command_mutations("git tag v1.0") or "")
    assert "git remote add is not permitted" in (check_read_only_command_mutations("git remote add upstream url") or "")


def test_tool_context_shell_widget_helpers():
    class DummyHost:
        def __init__(self):
            self.current_tool_widget = "dummy_widget"
            self._background_shell_widgets = {}
            self._foreground_shell_tasks = {}

    host = DummyHost()
    ctx = ToolContext(app=host, is_subagent=False)
    assert ctx.target_tool_widget == host.current_tool_widget

    subagent_ctx = ToolContext(app=host, is_subagent=True)
    assert subagent_ctx.target_tool_widget is None

    widget = MagicMock()
    ctx.attach_shell_widget("t1", widget, is_background=False)
    assert host._background_shell_widgets["t1"] == widget

    bg_widget = MagicMock()
    ctx.attach_shell_widget("t2", bg_widget, log_path="/tmp/t2.log", is_background=True)
    assert host._background_shell_widgets["t2"] == bg_widget
    bg_widget.mark_background.assert_called_once_with("t2", "/tmp/t2.log")

    ctx.detach_shell_widget("t1")
    assert "t1" not in host._background_shell_widgets

    task = MagicMock()
    ctx.register_foreground_shell_task("t_fg", task)
    assert host._foreground_shell_tasks["t_fg"] == task
    ctx.cleanup_foreground_shell_task("t_fg")
    assert "t_fg" not in host._foreground_shell_tasks

    # Test find_task & terminate_task_widget
    host._foreground_shell_tasks["fg1"] = task
    assert ctx.find_task("fg1") == task
    assert ctx.find_task("missing") is None

    host._background_shell_widgets["w1"] = widget
    ctx.terminate_task_widget("w1", output="killed!", status="done")
    assert "w1" not in host._background_shell_widgets
    widget.set_result.assert_called_with("killed!", status="done")


@pytest.mark.asyncio
async def test_terminate_process_tree_windows():
    from core.infrastructure.platform.process import terminate_process_tree

    proc = MagicMock()
    proc.pid = 1234
    proc.returncode = None
    proc.wait = AsyncMock()

    mock_sub = MagicMock()
    mock_sub.wait = AsyncMock()

    with (
        patch("core.infrastructure.platform.process.is_windows", return_value=True),
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_sub) as mock_exec,
    ):
        await terminate_process_tree(proc, timeout=0.5)
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "taskkill" in args
        assert "/T" in args
        assert "1234" in args


@pytest.mark.asyncio
async def test_terminate_process_tree_posix():
    from core.infrastructure.platform.process import terminate_process_tree

    proc = MagicMock()
    proc.pid = 4321
    proc.returncode = None
    proc.wait = AsyncMock()

    with (
        patch("core.infrastructure.platform.process.is_windows", return_value=False),
        patch("os.killpg") as mock_killpg,
    ):
        await terminate_process_tree(proc, timeout=0.5)
        mock_killpg.assert_called_once()
        args = mock_killpg.call_args[0]
        assert args[0] == 4321


def test_terminate_process_tree_sync_windows():
    from core.infrastructure.platform.process import terminate_process_tree_sync

    proc = MagicMock()
    proc.pid = 5678
    proc.returncode = None

    with (
        patch("core.infrastructure.platform.process.is_windows", return_value=True),
        patch("subprocess.run") as mock_run,
    ):
        terminate_process_tree_sync(proc)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "taskkill" in args
        assert "/PID" in args


