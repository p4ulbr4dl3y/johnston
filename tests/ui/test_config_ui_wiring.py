"""Regression tests: UI widgets honor config settings instead of hardcoded values."""

import asyncio

from core.infrastructure.config.settings import JohnstonSettings, UISettings
from widgets.chat_input import ChatInput
from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_messages import BotMessage, ThinkingWidget


def test_chat_input_max_prompt_history_respects_settings(monkeypatch):
    settings = JohnstonSettings(ui=UISettings(max_prompt_history=7))
    monkeypatch.setattr("widgets.chat_input.get_settings", lambda: settings)
    widget = ChatInput.__new__(ChatInput)
    assert widget.MAX_PROMPT_HISTORY == 7
    # per-instance override (existing tests assign this value) still wins
    widget.MAX_PROMPT_HISTORY = 3
    assert widget.MAX_PROMPT_HISTORY == 3


def test_chat_view_page_size_respects_settings(monkeypatch):
    settings = JohnstonSettings(ui=UISettings(chat_page_size=200))
    monkeypatch.setattr("widgets.presentation.widgets.chat_container.get_settings", lambda: settings)
    widget = ChatView.__new__(ChatView)
    assert widget.PAGE_SIZE == 200
    widget.PAGE_SIZE = 25
    assert widget.PAGE_SIZE == 25


def test_bot_message_stream_flush_interval_respects_settings(monkeypatch):
    settings = JohnstonSettings(ui=UISettings(stream_flush_interval=0.123))
    monkeypatch.setattr("widgets.presentation.widgets.chat_messages.get_settings", lambda: settings)
    captured = {}

    class FakeLoop:
        def call_later(self, delay, cb):
            captured["delay"] = delay
            captured["cb"] = cb
            return "handle"

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    widget = BotMessage.__new__(BotMessage)
    widget._stream_update_scheduled = False
    widget._schedule_stream_update()
    assert captured["delay"] == 0.123


def test_thinking_widget_stream_flush_interval_respects_settings(monkeypatch):
    settings = JohnstonSettings(ui=UISettings(stream_flush_interval=0.077))
    monkeypatch.setattr("widgets.presentation.widgets.chat_messages.get_settings", lambda: settings)
    captured = {}

    class FakeLoop:
        def call_later(self, delay, cb):
            captured["delay"] = delay
            captured["cb"] = cb
            return "handle"

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    widget = ThinkingWidget.__new__(ThinkingWidget)
    widget._update_scheduled = False
    widget.is_expanded = True
    widget._schedule_content_update()
    assert captured["delay"] == 0.077


def test_tool_call_widget_stream_flush_interval_respects_settings(monkeypatch):
    settings = JohnstonSettings(ui=UISettings(stream_flush_interval=0.077))
    monkeypatch.setattr("widgets.chat_toolcall.get_settings", lambda: settings)
    captured = {}

    class FakeLoop:
        def call_later(self, delay, cb):
            captured["delay"] = delay
            captured["cb"] = cb
            return "handle"

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    widget = ToolCallWidget.__new__(ToolCallWidget)
    widget._shell_update_scheduled = False
    widget._schedule_shell_update()
    assert captured["delay"] == 0.077
