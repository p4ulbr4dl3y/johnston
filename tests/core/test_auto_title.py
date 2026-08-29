"""Unit tests for session auto-titling logic."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from core.application.session.auto_title import (
    auto_title_session,
    clean_heuristic_title,
    extract_first_user_text,
    sanitize_title,
)
from core.domain.entities.session import AgentSession


class TestAutoTitleHelpers(unittest.TestCase):
    def test_clean_heuristic_title_empty(self):
        self.assertEqual(clean_heuristic_title(""), "")
        self.assertEqual(clean_heuristic_title("   "), "")

    def test_clean_heuristic_title_markdown_stripping(self):
        text = "# Fix ```python\ndef foo(): pass\n``` issue with `token_auth` and **login**!"
        cleaned = clean_heuristic_title(text)
        self.assertNotIn("```", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertIn("Fix issue with token_auth and login", cleaned)

    def test_clean_heuristic_title_truncation_word_boundary(self):
        long_prompt = "This is a very long user prompt that asks the agent to refactor the entire authentication subsystem"
        cleaned = clean_heuristic_title(long_prompt, max_len=40)
        self.assertTrue(len(cleaned) <= 43)
        self.assertTrue(cleaned.endswith("..."))
        self.assertFalse(cleaned.endswith(" ..."))

    def test_sanitize_title(self):
        self.assertEqual(sanitize_title(""), "")
        self.assertEqual(sanitize_title('  "Title: Fix JWT Expiration"  '), "Fix JWT Expiration")
        self.assertEqual(sanitize_title("### Topic: Database Connection Pooling."), "Database Connection Pooling")
        self.assertEqual(sanitize_title("`Refactor Auth Code`"), "Refactor Auth Code")

    def test_extract_first_user_text_from_messages(self):
        sess = AgentSession("s1")
        sess.messages = [
            {"type": "system", "text": "init"},
            {"type": "user", "text": "Inspect git status", "display_text": "Inspect git status"},
        ]
        self.assertEqual(extract_first_user_text(sess), "Inspect git status")

    def test_extract_first_user_text_from_agent_history(self):
        sess = AgentSession("s2")
        sess.agent_history = [
            {"role": "system", "content": "system prompt"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Check login flow"},
                ],
            },
        ]
        self.assertEqual(extract_first_user_text(sess), "Check login flow")

    def test_extract_first_user_text_empty(self):
        sess = AgentSession("s3")
        self.assertEqual(extract_first_user_text(sess), "")


class TestAutoTitleSessionAsync(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_existing_title(self):
        sess = AgentSession("s1", title="Manual Custom Title")
        sess.messages = [{"type": "user", "text": "Some text"}]
        res = await auto_title_session(None, sess)
        self.assertEqual(res, "Manual Custom Title")
        self.assertEqual(sess.title, "Manual Custom Title")

    async def test_empty_session_returns_none(self):
        sess = AgentSession("s2")
        res = await auto_title_session(None, sess)
        self.assertIsNone(res)

    async def test_fallback_heuristic_when_no_agent(self):
        sess = AgentSession("s3")
        sess.messages = [{"type": "user", "text": "Fix broken database migrations"}]
        res = await auto_title_session(None, sess)
        self.assertEqual(res, "Fix broken database migrations")
        self.assertEqual(sess._title, "Fix broken database migrations")
        self.assertEqual(sess.title, "Fix broken database migrations")

    async def test_llm_auto_titling_success(self):
        sess = AgentSession("s4")
        sess.messages = [{"type": "user", "text": "How do I optimize SQL query indexes for large user tables?"}]

        mock_agent = MagicMock()
        mock_agent.api_type = "openai"
        mock_agent.model = "gpt-4o"
        mock_agent.base_url = "https://api.openai.com/v1"
        mock_agent.api_key = "sk-test"
        mock_agent._client = None
        mock_agent.headers = {}

        mock_adapter = MagicMock()

        async def fake_stream(**kwargs):
            yield ("adapter_text", "Optimize SQL Query Indexes")

        mock_adapter.stream_chat = MagicMock(side_effect=fake_stream)

        with patch("core.adapters.get_adapter", return_value=mock_adapter):
            res = await auto_title_session(mock_agent, sess)

        self.assertEqual(res, "Optimize SQL Query Indexes")
        self.assertEqual(sess._title, "Optimize SQL Query Indexes")
        self.assertEqual(sess.title, "Optimize SQL Query Indexes")

    async def test_llm_auto_titling_fallback_on_error(self):
        sess = AgentSession("s5")
        sess.messages = [{"type": "user", "text": "Deploy to production Kubernetes cluster"}]

        mock_agent = MagicMock()
        mock_agent.api_type = "openai"
        mock_agent.model = "gpt-4o"

        with patch("core.adapters.get_adapter", side_effect=RuntimeError("API error")):
            res = await auto_title_session(mock_agent, sess)

        self.assertEqual(res, "Deploy to production Kubernetes cluster")
        self.assertEqual(sess._title, "Deploy to production Kubernetes cluster")

    async def test_disabled_by_settings(self):
        sess = AgentSession("s6")
        sess.messages = [{"type": "user", "text": "Hello world"}]

        with patch("core.application.session.auto_title.get_settings") as mock_settings:
            mock_settings.return_value.llm.auto_title = False
            res = await auto_title_session(None, sess)

        self.assertIsNone(res)
        self.assertEqual(sess._title, "")


class TestMessageFlowAutoTitle(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_auto_title_invokes_and_saves(self):
        from widgets.mixins.message_flow import MessageFlowMixin

        class DummyApp(MessageFlowMixin):
            def __init__(self):
                self.is_app_active = True
                self.current_session_id = "s-test"
                self.agent = None
                self.sm = MagicMock()
                self.footer_refreshed = False

            def refresh_status_footer(self):
                self.footer_refreshed = True

        app = DummyApp()
        sess = AgentSession("s-test")
        sess.messages = [{"type": "user", "text": "Test auto titling integration"}]

        app._schedule_auto_title(sess)
        await asyncio.sleep(0.05)

        self.assertEqual(sess.title, "Test auto titling integration")
        app.sm.save.assert_called_with(sess)
        self.assertTrue(app.footer_refreshed)
