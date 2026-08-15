"""Edge-case tests for widgets/chat_messages.

Detectors for real bugs in empty/whitespace/None message content handling.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from widgets.presentation.widgets.chat_messages import BotMessage, EventDivider, UserMessage


class TestEventHandler(unittest.TestCase):
    class _FakeRule:
        def __init__(self, title, style=None):
            self.title = title

    def test_event_divider_update_title_updates_rule(self):
        divider = EventDivider("Old")
        divider._content = self._FakeRule("Old")
        divider.update = MagicMock()
        divider.update_title("New")
        self.assertEqual(divider.divider_title, "New")
        divider.update.assert_called_once()
        args = divider.update.call_args[0][0]
        self.assertEqual(args.title, "New")


class TestBotMessageEmptyContent(unittest.IsolatedAsyncioTestCase):
    def test_set_stream_content_whitespace_only_keeps_streaming(self):
        msg = BotMessage()
        msg.set_stream_content("   ")
        self.assertTrue(msg._streaming)

    async def test_set_final_content_empty_persists_clean(self):
        msg = BotMessage()
        msg.stream_widget.update = MagicMock()
        msg.md_widget.update = AsyncMock(return_value=None)
        with patch.object(type(msg.md_widget), "is_attached", new_callable=PropertyMock, return_value=False):
            await msg.set_final_content("")
        self.assertFalse(msg._streaming)


class TestBotMessageMarkdownRender(unittest.IsolatedAsyncioTestCase):
    async def test_render_markdown_empty_content(self):
        msg = BotMessage()
        msg.md_widget.update = AsyncMock(return_value=None)
        with patch.object(type(msg.md_widget), "is_attached", new_callable=PropertyMock, return_value=True):
            await msg._render_markdown("")
        msg.md_widget.update.assert_awaited_once_with("")


class TestUserMessage(unittest.TestCase):
    def test_whitespace_content_no_raise(self):
        # Whitespace content renders without crashing.
        msg = UserMessage("   ", markup=False)
        self.assertEqual(msg.raw_text, "   ")


if __name__ == "__main__":
    unittest.main()
