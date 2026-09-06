"""Tests for Johnston CLI session command."""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from core.domain.entities.session import AgentSession, SessionStatus
from core.interfaces.cli.commands.session_cmd import (
    export_session,
    list_sessions,
    prune_sessions,
    rm_session,
    run_session,
)
from core.interfaces.cli.entrypoint import main


class TestCLISession(unittest.TestCase):
    def setUp(self):
        self.mock_store = MagicMock()

    def test_list_sessions_empty(self):
        self.mock_store.list_main_sessions.return_value = []
        self.mock_store.list.return_value = []

        out = io.StringIO()
        with redirect_stdout(out):
            code = list_sessions(store=self.mock_store)

        self.assertEqual(code, 0)
        self.assertIn("No sessions found.", out.getvalue())

    def test_list_sessions_formatted_table(self):
        self.mock_store.list_main_sessions.return_value = [
            {
                "id": "sess-1234",
                "title": "Short title",
                "message_count": 5,
                "updated_at": 1700000000.0,
            },
            {
                "id": "sess-5678",
                "title": "A" * 80,
                "turn_count": 2,
                "updated_at": None,
                "created_at": 1600000000.0,
            },
        ]

        out = io.StringIO()
        with redirect_stdout(out):
            code = list_sessions(store=self.mock_store)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("Session ID", output)
        self.assertIn("Title", output)
        self.assertIn("Messages count", output)
        self.assertIn("Last Updated", output)
        self.assertIn("sess-1234", output)
        self.assertIn("Short title", output)
        self.assertIn("sess-5678", output)
        self.assertIn("...", output)  # Truncated title

    def test_list_sessions_limit(self):
        self.mock_store.list_main_sessions.return_value = [
            {"id": f"sess-{i}", "title": f"Title {i}", "message_count": i, "updated_at": 1700000000.0}
            for i in range(10)
        ]

        out = io.StringIO()
        with redirect_stdout(out):
            code = list_sessions(limit=3, store=self.mock_store)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("sess-0", output)
        self.assertIn("sess-1", output)
        self.assertIn("sess-2", output)
        self.assertNotIn("sess-3", output)

    def test_list_sessions_fallback_disk(self):
        self.mock_store.list_main_sessions.return_value = []
        sess = AgentSession(session_id="fallback-1", title="Fallback Session", created_at=1700000000.0)
        self.mock_store.list.return_value = [sess]

        out = io.StringIO()
        with redirect_stdout(out):
            code = list_sessions(store=self.mock_store)

        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("fallback-1", output)
        self.assertIn("Fallback Session", output)

    def test_rm_session_missing_id(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = rm_session("", store=self.mock_store)

        self.assertEqual(code, 1)
        self.assertIn("Error: Session ID is required.", err.getvalue())

    def test_rm_session_not_found(self):
        self.mock_store.get.return_value = None
        self.mock_store.find_session_by_title_or_id.return_value = None

        err = io.StringIO()
        with redirect_stderr(err):
            code = rm_session("non-existent", store=self.mock_store)

        self.assertEqual(code, 1)
        self.assertIn("Error: Session 'non-existent' not found.", err.getvalue())

    def test_rm_session_success(self):
        sess = AgentSession(session_id="target-sess")
        self.mock_store.get.return_value = sess

        out = io.StringIO()
        with redirect_stdout(out):
            code = rm_session("target-sess", store=self.mock_store)

        self.assertEqual(code, 0)
        self.mock_store.delete.assert_called_once_with("target-sess")
        self.assertIn("Session 'target-sess' deleted.", out.getvalue())

    def test_rm_session_by_title(self):
        sess = AgentSession(session_id="target-by-title", title="My Title")
        self.mock_store.get.return_value = None
        self.mock_store.find_session_by_title_or_id.return_value = sess

        out = io.StringIO()
        with redirect_stdout(out):
            code = rm_session("My Title", store=self.mock_store)

        self.assertEqual(code, 0)
        self.mock_store.delete.assert_called_once_with("target-by-title")
        self.assertIn("Session 'target-by-title' deleted.", out.getvalue())

    def test_prune_sessions_negative_days(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = prune_sessions(days=-1, store=self.mock_store)

        self.assertEqual(code, 1)
        self.assertIn("Error: Days must be non-negative.", err.getvalue())

    def test_prune_sessions_prunes_older(self):
        now = time.time()
        old_sess1 = AgentSession(session_id="old-1", updated_at=now - (20 * 86400))
        old_sess2 = AgentSession(session_id="old-2", created_at=now - (15 * 86400))
        recent_sess = AgentSession(session_id="recent", updated_at=now - (2 * 86400))

        self.mock_store.list.return_value = [old_sess1, old_sess2, recent_sess]

        out = io.StringIO()
        with redirect_stdout(out):
            code = prune_sessions(days=14, store=self.mock_store)

        self.assertEqual(code, 0)
        self.mock_store.delete.assert_any_call("old-1")
        self.mock_store.delete.assert_any_call("old-2")
        self.assertIn("Pruned 2 session(s) older than 14 days.", out.getvalue())

    def test_prune_sessions_none_older(self):
        now = time.time()
        recent_sess = AgentSession(session_id="recent", updated_at=now - (1 * 86400))
        self.mock_store.list.return_value = [recent_sess]

        out = io.StringIO()
        with redirect_stdout(out):
            code = prune_sessions(days=14, store=self.mock_store)

        self.assertEqual(code, 0)
        self.assertEqual(self.mock_store.delete.call_count, 0)
        self.assertIn("Pruned 0 session(s) older than 14 days.", out.getvalue())

    def test_export_session_missing_id(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = export_session("", store=self.mock_store)

        self.assertEqual(code, 1)
        self.assertIn("Error: Session ID is required.", err.getvalue())

    def test_export_session_not_found(self):
        self.mock_store.get.return_value = None
        self.mock_store.find_session_by_title_or_id.return_value = None

        err = io.StringIO()
        with redirect_stderr(err):
            code = export_session("non-existent", store=self.mock_store)

        self.assertEqual(code, 1)
        self.assertIn("Error: Session 'non-existent' not found.", err.getvalue())

    def test_export_session_json(self):
        sess = AgentSession(
            session_id="export-json",
            title="JSON Test",
            role="worker",
            status=SessionStatus.ACTIVE,
            created_at=1700000000.0,
        )
        sess.messages = [
            {"type": "user", "text": "hello"},
            {"type": "bot", "text": "world"},
        ]
        self.mock_store.get.return_value = sess

        out = io.StringIO()
        with redirect_stdout(out):
            code = export_session("export-json", format_="json", store=self.mock_store)

        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["id"], "export-json")
        self.assertEqual(len(data["messages"]), 2)

    def test_export_session_markdown(self):
        sess = AgentSession(
            session_id="export-md",
            title="Markdown Test",
            role="worker",
            status=SessionStatus.ACTIVE,
            created_at=1700000000.0,
            updated_at=1700000100.0,
        )
        sess.messages = [
            {"type": "user", "text": "Can you check files?", "show_in_ui": True},
            {"type": "thinking", "text": "Let me think"},
            {
                "type": "tool",
                "tool_type": "view_file",
                "args": {"path": "test.txt"},
                "result_text": "file content here",
            },
            {"type": "bot", "text": "Here is what I found."},
            {"type": "event_divider", "text": "Turn Completed"},
        ]
        self.mock_store.get.return_value = sess

        out = io.StringIO()
        with redirect_stdout(out):
            code = export_session("export-md", format_="md", store=self.mock_store)

        self.assertEqual(code, 0)
        content = out.getvalue()
        self.assertIn("# Session: Markdown Test", content)
        self.assertIn("- **Session ID:** export-md", content)
        self.assertIn("### User\n\nCan you check files?", content)
        self.assertIn("> *Thinking: Let me think*", content)
        self.assertIn("**Tool Call:** `view_file`", content)
        self.assertIn("file content here", content)
        self.assertIn("### Assistant\n\nHere is what I found.", content)
        self.assertIn("*[Turn Completed]*", content)

    def test_export_session_markdown_history_fallback(self):
        sess = AgentSession(
            session_id="export-hist",
            title="History Fallback",
            created_at=1700000000.0,
        )
        sess.messages = []
        sess.agent_history = [
            {"role": "user", "content": "history user turn"},
            {"role": "assistant", "content": "history assistant response"},
        ]
        self.mock_store.get.return_value = sess

        out = io.StringIO()
        with redirect_stdout(out):
            code = export_session("export-hist", format_="md", store=self.mock_store)

        self.assertEqual(code, 0)
        content = out.getvalue()
        self.assertIn("### User\n\nhistory user turn", content)
        self.assertIn("### Assistant\n\nhistory assistant response", content)

    def test_export_session_to_file(self):
        sess = AgentSession(session_id="file-export", title="File Output Test")
        sess.messages = [{"type": "user", "text": "hello"}]
        self.mock_store.get.return_value = sess

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "subdir", "session.md")
            out = io.StringIO()
            with redirect_stdout(out):
                code = export_session(
                    "file-export",
                    format_="md",
                    output_file=out_file,
                    store=self.mock_store,
                )

            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out_file))
            with open(out_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("# Session: File Output Test", content)
            self.assertIn("Session 'file-export' exported to", out.getvalue())

    def test_export_session_write_error(self):
        sess = AgentSession(session_id="file-err", title="Err Test")
        self.mock_store.get.return_value = sess

        err = io.StringIO()
        with redirect_stderr(err):
            with patch("builtins.open", side_effect=OSError("Permission denied")):
                code = export_session(
                    "file-err",
                    output_file="/nonexistent/dir/file.md",
                    store=self.mock_store,
                )

        self.assertEqual(code, 1)
        self.assertIn("Error writing to", err.getvalue())

    def test_run_session_dispatcher(self):
        args_list = MagicMock(session_action="list", limit=5)
        with patch("core.interfaces.cli.commands.session_cmd.list_sessions", return_value=0) as m_list:
            self.assertEqual(run_session(args_list, store=self.mock_store), 0)
            m_list.assert_called_once_with(limit=5, store=self.mock_store)

        args_rm = MagicMock(session_action="rm", session_id="s1")
        with patch("core.interfaces.cli.commands.session_cmd.rm_session", return_value=0) as m_rm:
            self.assertEqual(run_session(args_rm, store=self.mock_store), 0)
            m_rm.assert_called_once_with("s1", store=self.mock_store)

        args_prune = MagicMock(session_action="prune", days=7)
        with patch("core.interfaces.cli.commands.session_cmd.prune_sessions", return_value=0) as m_prune:
            self.assertEqual(run_session(args_prune, store=self.mock_store), 0)
            m_prune.assert_called_once_with(days=7, store=self.mock_store)

        args_export = MagicMock(session_action="export", session_id="s2", format="json", output="out.json")
        with patch("core.interfaces.cli.commands.session_cmd.export_session", return_value=0) as m_exp:
            self.assertEqual(run_session(args_export, store=self.mock_store), 0)
            m_exp.assert_called_once_with("s2", format_="json", output_file="out.json", store=self.mock_store)

        args_unknown = MagicMock(session_action="invalid")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(run_session(args_unknown, store=self.mock_store), 1)
        self.assertIn("Error: Unknown session action 'invalid'", err.getvalue())

    def test_cli_session_via_main(self):
        with patch("core.interfaces.cli.commands.session_cmd.run_session", return_value=0) as m_run:
            with self.assertRaises(SystemExit) as cm:
                main(["session", "list", "--limit", "10"])
            self.assertEqual(cm.exception.code, 0)
            self.assertEqual(m_run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
