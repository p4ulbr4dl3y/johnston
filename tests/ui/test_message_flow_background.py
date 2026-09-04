import unittest
from unittest.mock import MagicMock, patch

import pytest

from app import JohnstonApp


@pytest.mark.slow
class TestBackgroundShellCompleted(unittest.IsolatedAsyncioTestCase):
    async def test_completed_not_active_returns(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_app_active = False
            app.on_background_shell_completed("t1", "ls", "out")

    async def test_completed_generating_queues(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True
            app.current_session_id = "s1"
            app.on_background_shell_completed("t1", "ls", "out")
            self.assertEqual(len(app.message_queue), 1)
            self.assertEqual(app.message_queue[0][3], "s1")

    async def test_completed_exception(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            with patch.object(app, "generate_ai_response", side_effect=Exception("boom")):
                app.on_background_shell_completed("t1", "ls", "out")

    async def test_completed_truncates_tail(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            sent = []
            with patch.object(app, "generate_ai_response", side_effect=lambda msg, **k: sent.append(msg)):
                app.on_background_shell_completed("t1", "ls", "x" * 5000)
            self.assertEqual(len(sent), 1)
            self.assertIn("[truncated", sent[0])
            self.assertIn("x" * 4000, sent[0])
            self.assertNotIn("x" * 5000, sent[0].strip(" \n[].<>"))

    async def test_completed_updates_widget_done(self):
        from core.infrastructure.tasks.shell_task import ShellTask
        from core.infrastructure.tasks.task import TaskStatus

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            widget = MagicMock()
            task = ShellTask("t1", "ls")
            task.status = TaskStatus.COMPLETED
            app.task_manager.register(task)
            app._background_shell_widgets["t1"] = widget
            with patch.object(app, "generate_ai_response"):
                app.on_background_shell_completed("t1", "ls", "some output")
            widget.set_result.assert_called_once_with("some output", status="done")

    async def test_completed_updates_widget_error(self):
        from core.infrastructure.tasks.shell_task import ShellTask
        from core.infrastructure.tasks.task import TaskStatus

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            widget = MagicMock()
            task = ShellTask("t1", "ls")
            task.status = TaskStatus.ERROR
            app.task_manager.register(task)
            app._background_shell_widgets["t1"] = widget
            with patch.object(app, "generate_ai_response"):
                app.on_background_shell_completed("t1", "ls", "ERR: command failed")
            widget.set_result.assert_called_once_with("ERR: command failed", status="error")

    async def test_completed_no_widget_noop(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            with patch.object(app, "generate_ai_response"):
                app.on_background_shell_completed("missing", "ls", "out")
            self.assertEqual(len(app.message_queue), 0)

    async def test_subagent_completed_widget_done(self):
        from unittest.mock import MagicMock

        app = JohnstonApp()
        async with app.run_test():
            widget = MagicMock()
            app._subagent_tools["s1"] = widget
            app.on_subagent_tool_completed("s1", "completed", "ok result")
            widget.set_result.assert_called_once_with("ok result", status="done")

    async def test_subagent_completed_widget_error(self):
        from unittest.mock import MagicMock

        app = JohnstonApp()
        async with app.run_test():
            widget = MagicMock()
            app._subagent_tools["s1"] = widget
            app.on_subagent_tool_completed("s1", "error", "boom")
            widget.set_result.assert_called_once_with("boom", status="error")

    async def test_subagent_completed_widget_cancelled(self):
        from unittest.mock import MagicMock

        app = JohnstonApp()
        async with app.run_test():
            widget = MagicMock()
            app._subagent_tools["s1"] = widget
            app.on_subagent_tool_completed("s1", "cancelled")
            widget.mark_cancelled.assert_called_once()

    async def test_subagent_completed_unknown_widget_noop(self):
        app = JohnstonApp()
        async with app.run_test():
            # No widget registered for this session: must not raise.
            app.on_subagent_tool_completed("missing", "completed", "out")
            self.assertEqual(len(app.message_queue), 0)

    async def test_completed_updates_session_messages(self):
        from core.infrastructure.tasks.shell_task import ShellTask
        from core.infrastructure.tasks.task import TaskStatus

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            task = ShellTask("shell_123_1", "ls")
            task.status = TaskStatus.COMPLETED
            app.task_manager.register(task)

            session = app.sm.create_main(app.current_session_id)
            session.messages = [
                {
                    "type": "tool",
                    "tool_type": "shell",
                    "result_text": "[Background Task ID: shell_123_1] 'ls' moved to background.",
                    "status": "running",
                }
            ]
            app.sm.save(session)

            with patch.object(app, "generate_ai_response"):
                app.on_background_shell_completed("shell_123_1", "ls", "file1.txt\nfile2.txt")

            updated = app.sm.get(app.current_session_id)
            self.assertEqual(updated.messages[0]["status"], "done")
            self.assertEqual(updated.messages[0]["result_text"], "file1.txt\nfile2.txt")

    async def test_subagent_completed_updates_session_messages(self):
        app = JohnstonApp()
        async with app.run_test():
            session = app.sm.create_main(app.current_session_id)
            session.messages = [
                {
                    "type": "tool",
                    "tool_type": "invoke_subagent",
                    "args": {"description": "worker", "prompt": "do work"},
                    "result_text": "subagent 'worker' launched (session_id: sub_999)",
                    "status": "running",
                }
            ]
            app.sm.save(session)

            app.on_subagent_tool_completed("sub_999", "completed", "done work")

            updated = app.sm.get(app.current_session_id)
            self.assertEqual(updated.messages[0]["status"], "done")
            self.assertEqual(updated.messages[0]["result_text"], "done work")

    async def test_progress_generating_queues_running_notification(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True
            app.current_session_id = "s1"
            app.on_background_shell_progress("t1", "make", "compiling...", event="inactivity", idle_seconds=30)
            self.assertEqual(len(app.message_queue), 1)
            msg = app.message_queue[0][0]
            self.assertIn('status="running"', msg)
            self.assertIn('event="inactivity"', msg)
            self.assertIn('idle_seconds="30"', msg)
            self.assertIn("[process running with no output for 30s]", msg)

    async def test_progress_not_generating_triggers_response(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            sent = []
            with patch.object(app, "generate_ai_response", side_effect=lambda msg, **k: sent.append(msg)):
                app.on_background_shell_progress("t1", "make", "still working", event="inactivity", idle_seconds=60)
            self.assertEqual(len(sent), 1)
            self.assertIn('status="running"', sent[0])
            self.assertIn('idle_seconds="60"', sent[0])

    async def test_completed_timed_out_adds_state_hint(self):
        from core.infrastructure.tasks.shell_task import ShellTask

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            task = ShellTask("t_to", "long_job", hard_timeout=120)
            task.timed_out = True
            app.task_manager.register(task)
            sent = []
            with patch.object(app, "generate_ai_response", side_effect=lambda msg, **k: sent.append(msg)):
                app.on_background_shell_completed("t_to", "long_job", "output before timeout")
            self.assertEqual(len(sent), 1)
            self.assertIn("[status: error | timed out after 120s]", sent[0])
            self.assertIn('status="error"', sent[0])

    async def test_completed_killed_normalizes_to_cancelled(self):
        from core.infrastructure.tasks.shell_task import ShellTask
        from core.infrastructure.tasks.task import TaskStatus

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            task = ShellTask("t_kill", "sleep 100")
            task.status = TaskStatus.KILLED
            task.was_killed = True
            app.task_manager.register(task)
            sent = []
            with patch.object(app, "generate_ai_response", side_effect=lambda msg, **k: sent.append(msg)):
                app.on_background_shell_completed("t_kill", "sleep 100", "killed output")
            self.assertEqual(len(sent), 1)
            self.assertIn('status="cancelled"', sent[0])
            self.assertNotIn('status="killed"', sent[0])

    async def test_completed_suppressed_notification_skips_ai(self):
        from core.infrastructure.tasks.shell_task import ShellTask
        from core.infrastructure.tasks.task import TaskStatus

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            task = ShellTask("t_supp", "sleep 100")
            task.status = TaskStatus.KILLED
            task.suppress_notification = True
            app.task_manager.register(task)
            sent = []
            with patch.object(app, "generate_ai_response", side_effect=lambda msg, **k: sent.append(msg)):
                app.on_background_shell_completed("t_supp", "sleep 100", "killed output")
            self.assertEqual(len(sent), 0)
            self.assertEqual(len(app.message_queue), 0)

    async def test_completed_cross_session_queues_to_task_session(self):
        from core.infrastructure.tasks.shell_task import ShellTask
        from core.infrastructure.tasks.task import TaskStatus

        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            app.current_session_id = "sess_B"
            task = ShellTask("t_diff", "ls", session_id="sess_A")
            task.status = TaskStatus.COMPLETED
            app.task_manager.register(task)
            with patch.object(app, "generate_ai_response") as mock_gen:
                app.on_background_shell_completed("t_diff", "ls", "ok")
                mock_gen.assert_not_called()
            self.assertEqual(len(app.message_queue), 1)
            self.assertEqual(app.message_queue[0][3], "sess_A")


if __name__ == "__main__":
    unittest.main()
