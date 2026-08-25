import time
import unittest
from unittest.mock import MagicMock

from core.infrastructure.presentation.tool_display import (
    _format_active_tool_progress,
    extract_subagent_progress,
)
from widgets.presentation.screens.tasks import (
    extract_shell_task_progress,
    format_shell_task_row,
    format_subagent_task_row,
)


class TestSubagentProgressDisplay(unittest.TestCase):
    def test_extract_progress_none_or_empty(self):
        self.assertEqual(extract_subagent_progress(None), "")
        sess = MagicMock()
        sess.is_running = False
        sess.status = "completed"
        sess.step_count = 1
        self.assertEqual(extract_subagent_progress(sess), "done • 1 step")
        sess.step_count = 5
        self.assertEqual(extract_subagent_progress(sess), "done • 5 steps")
        sess.step_count = 0
        sess.agent_history = [{"role": "assistant"}]
        sess.messages = []
        self.assertEqual(extract_subagent_progress(sess), "done • 1 step")
        sess.agent_history = [{"role": "assistant"}, {"role": "assistant"}, {"role": "assistant"}]
        self.assertEqual(extract_subagent_progress(sess), "done • 3 steps")
        sess.agent_history = []
        self.assertEqual(extract_subagent_progress(sess), "done")
        sess.status = "cancelled"
        self.assertEqual(extract_subagent_progress(sess), "cancelled")
        sess.status = "error"
        self.assertEqual(extract_subagent_progress(sess), "error")

    def test_extract_progress_running_starting(self):
        sess = MagicMock()
        sess.is_running = True
        sess.status = "running"
        sess.messages = []
        self.assertEqual(extract_subagent_progress(sess), "starting...")
        sess.messages = [{"type": "user", "text": "do something"}]
        self.assertEqual(extract_subagent_progress(sess), "starting...")

    def test_extract_progress_thinking(self):
        sess = MagicMock()
        sess.is_running = True
        sess.status = "running"
        sess.messages = [{"type": "thinking", "text": "hmm"}]
        self.assertEqual(extract_subagent_progress(sess), "thinking...")

    def test_extract_progress_bot(self):
        sess = MagicMock()
        sess.is_running = True
        sess.status = "running"
        sess.messages = [{"type": "bot", "text": "hello"}]
        self.assertEqual(extract_subagent_progress(sess), "generating...")

    def test_extract_progress_tool_active(self):
        sess = MagicMock()
        sess.is_running = True
        sess.status = "running"
        # read single
        sess.messages = [{"type": "tool", "tool_type": "read", "args": {"path": "core/session_manager.py"}}]
        self.assertEqual(extract_subagent_progress(sess), "reading file")
        # read multiple files in batch
        sess.messages = [
            {"type": "tool", "tool_type": "read", "args": {"path": "core/session_manager.py"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "view_file", "args": {"path": "core/app.py"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "read", "args": {"path": "core/test.py"}},
        ]
        self.assertEqual(extract_subagent_progress(sess), "reading 3 files")
        # multiple reads to same file -> 1 file
        sess.messages = [
            {"type": "tool", "tool_type": "read", "args": {"path": "core/session_manager.py"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "read", "args": {"path": "core/session_manager.py"}},
        ]
        self.assertEqual(extract_subagent_progress(sess), "reading file")

        # create single
        sess.messages = [{"type": "tool", "tool_type": "create", "args": {"path": "tests/test_foo.py"}}]
        self.assertEqual(extract_subagent_progress(sess), "creating file")
        # create multiple
        sess.messages = [
            {"type": "tool", "tool_type": "create", "args": {"path": "a.py"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "write_to_file", "args": {"path": "b.py"}},
        ]
        self.assertEqual(extract_subagent_progress(sess), "creating 2 files")

        # edit single
        sess.messages = [{"type": "tool", "tool_type": "edit", "args": {"path": "widgets/app.py"}}]
        self.assertEqual(extract_subagent_progress(sess), "editing file")
        # edit multiple
        sess.messages = [
            {"type": "tool", "tool_type": "edit", "args": {"path": "a.py"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "replace_file_content", "args": {"path": "b.py"}},
        ]
        self.assertEqual(extract_subagent_progress(sess), "editing 2 files")

        # shell single
        sess.messages = [{"type": "tool", "tool_type": "shell", "args": {"command": "uv run pytest -k test_app"}}]
        self.assertEqual(extract_subagent_progress(sess), "running command")
        # shell multiple
        sess.messages = [
            {"type": "tool", "tool_type": "shell", "args": {"command": "cd /tmp && pytest"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "run_command", "args": {"command": "git status"}},
        ]
        self.assertEqual(extract_subagent_progress(sess), "running 2 commands")

        # update_plan
        sess.messages = [
            {
                "type": "tool",
                "tool_type": "update_plan",
                "args": {"plan": [{"status": "completed"}, {"status": "in_progress"}]},
            }
        ]
        self.assertEqual(extract_subagent_progress(sess), "plan [1/2]")

        # web_fetch single & search multi
        sess.messages = [
            {"type": "tool", "tool_type": "web_fetch", "args": {"url": "https://docs.python.org/3/library"}}
        ]
        self.assertEqual(extract_subagent_progress(sess), "fetching web")
        sess.messages = [
            {"type": "tool", "tool_type": "search_web", "args": {"query": "python"}, "result_text": "ok"},
            {"type": "tool", "tool_type": "search_web", "args": {"query": "textual"}},
        ]
        self.assertEqual(extract_subagent_progress(sess), "searching web (2)")

    def test_extract_progress_completed_tool_means_generating(self):
        sess = MagicMock()
        sess.is_running = True
        sess.status = "running"
        sess.messages = [
            {"type": "tool", "tool_type": "read", "args": {"path": "a.py"}, "result_text": "contents of file"}
        ]
        self.assertEqual(extract_subagent_progress(sess), "generating...")

    def test_format_active_tool_generic(self):
        self.assertEqual(_format_active_tool_progress("custom_mcp_query", {}), "tool: custom_mcp_query")
        self.assertEqual(_format_active_tool_progress("", {}), "running...")

    def test_format_subagent_task_row(self):
        sess = MagicMock()
        sess.is_running = True
        sess.status = "running"
        sess.messages = [{"type": "tool", "tool_type": "read", "args": {"path": "test.py"}}]
        row = format_subagent_task_row("Research codebase structure", session=sess, is_running=True)
        self.assertIn("Research codebase structure", row)
        self.assertIn("reading file", row)
        self.assertIn("[dim #71717a]", row)


class TestShellTaskProgressDisplay(unittest.TestCase):
    def test_extract_shell_progress_none(self):
        self.assertEqual(extract_shell_task_progress(None), "")

    def test_extract_shell_progress_running(self):
        task = MagicMock()
        task.is_running = True
        task.created_at = time.time() - 15.0
        self.assertEqual(extract_shell_task_progress(task), "running • 15s")
        task.created_at = None
        self.assertEqual(extract_shell_task_progress(task), "running...")

    def test_extract_shell_progress_completed(self):
        task = MagicMock()
        task.is_running = False
        task.was_killed = False
        task.status = "completed"
        task.created_at = 100.0
        task.completed_at = 104.2
        task.exit_code = 0
        self.assertEqual(extract_shell_task_progress(task), "exit 0 • 4.2s")

        task.exit_code = 1
        self.assertEqual(extract_shell_task_progress(task), "exit 1 • 4.2s")

    def test_extract_shell_progress_killed_and_timeout(self):
        task = MagicMock()
        task.is_running = False
        task.was_killed = True
        task.status = "killed"
        self.assertEqual(extract_shell_task_progress(task), "killed")

        task.was_killed = False
        task.status = "timeout"
        self.assertEqual(extract_shell_task_progress(task), "timeout")

    def test_format_shell_task_row(self):
        task = MagicMock()
        task.is_running = False
        task.was_killed = False
        task.status = "completed"
        task.created_at = 100.0
        task.completed_at = 142.0
        task.exit_code = 0
        row = format_shell_task_row("uv run pytest -n auto", task=task, is_running=False)
        self.assertIn("uv run pytest -n auto", row)
        self.assertIn("exit 0 • 42s", row)
        self.assertIn("[dim #71717a]", row)


if __name__ == "__main__":
    unittest.main()

