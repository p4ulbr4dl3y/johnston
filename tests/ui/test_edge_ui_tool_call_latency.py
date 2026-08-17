"""Latency and event-loop lag tests for tool calls in the UI pipeline.

Tracks event-loop responsiveness (heartbeat drift) during tool widget creation,
result rendering, streaming pipeline events, and execution to detect UI freezes.
"""
from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any, Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

from app import JohnstonApp
from core.application.generation.ai_generator import GenCanvas, generate_ai_response
from core.base_provider import BaseAgent
from tools.registry import execute_tool
from widgets.presentation.widgets.chat_container import ChatView


async def measure_event_loop_lag(
    async_work: Callable[[], Awaitable[Any]],
    tick: float = 0.005,
) -> tuple[Any, float]:
    """Execute ``async_work`` while monitoring event loop lag.

    Runs a high-resolution background ticker. If synchronous code blocks the
    Textual/asyncio event loop, the ticker wakes up late and records the drift.

    Returns ``(result, max_lag_seconds)``.
    """
    max_lag = 0.0
    stop = False

    async def _heartbeat():
        nonlocal max_lag
        while not stop:
            t0 = time.perf_counter()
            await asyncio.sleep(tick)
            elapsed = time.perf_counter() - t0
            lag = elapsed - tick
            if lag > max_lag:
                max_lag = lag

    monitor_task = asyncio.create_task(_heartbeat())
    try:
        res = await async_work()
    finally:
        stop = True
        await monitor_task

    return res, max_lag


def _create_fake_session():
    session = MagicMock()
    session.events = []
    session.add_event = session.events.append
    return session


class TestToolCallLatency(unittest.IsolatedAsyncioTestCase):
    # Threshold for event loop stall: > 250ms catches real UI freezes while tolerating parallel xdist test runner load
    MAX_ALLOWED_LAG_SECONDS = 0.250

    async def test_tool_call_mount_responsiveness(self):
        """Mounting ToolCallWidgets for different tools must not block event loop."""
        app = JohnstonApp()
        async with app.run_test():
            chat_view = app.query_one(ChatView)

            test_cases = [
                ("read", "core/application/generation/ai_generator.py", {"path": "ai_generator.py"}),
                ("shell", "pytest -q", {"command": "pytest -q"}),
                ("create", "new_file.py", {"path": "new_file.py", "content": "print('hello')\n" * 50}),
                ("edit", "old_file.py", {"path": "old_file.py", "old_str": "a", "new_str": "b"}),
                ("update_plan", "Plan", {"plan": [{"step": "step1", "status": "in_progress"}]}),
                ("mcp_custom_tool", "arg_value", {"query": "search query", "limit": 10}),
            ]

            for tool_type, target, args in test_cases:
                async def _mount():
                    return await chat_view.add_tool_call(tool_type, target, args=args, animate=False)

                widget, lag = await measure_event_loop_lag(_mount)
                self.assertIsNotNone(widget)
                self.assertLess(
                    lag,
                    self.MAX_ALLOWED_LAG_SECONDS,
                    f"Mounting tool '{tool_type}' froze UI for {lag * 1000:.1f}ms (> {self.MAX_ALLOWED_LAG_SECONDS * 1000}ms)",
                )

    async def test_tool_call_result_render_responsiveness(self):
        """Updating tool results (including large outputs and diffs) must not freeze UI."""
        app = JohnstonApp()
        async with app.run_test():
            chat_view = app.query_one(ChatView)
            widget = await chat_view.add_tool_call("shell", "git status", animate=False)

            large_output = "Line content output with some numbers 12345\n" * 300

            async def _update_result():
                widget.set_result(large_output, is_error=False, status="done")
                await asyncio.sleep(0)

            _, lag = await measure_event_loop_lag(_update_result)
            self.assertLess(
                lag,
                self.MAX_ALLOWED_LAG_SECONDS,
                f"Setting tool result froze UI for {lag * 1000:.1f}ms",
            )

    async def test_generation_pipeline_tool_call_stream_responsiveness(self):
        """Full AI generator stream handling ('tool' + 'tool_result' events) must not stall UI."""
        app = JohnstonApp()
        async with app.run_test():
            chat_view = app.query_one(ChatView)
            canvas = GenCanvas(
                add_user_message=lambda text, atts: chat_view.add_user_message(text, attachments=atts),
                add_thinking_widget=chat_view.add_thinking_widget,
                add_tool_call=lambda name, desc, args: chat_view.add_tool_call(name, desc, args=args, animate=False),
                register_tool_widget=MagicMock(),
                add_bot_message=lambda animate=False: chat_view.add_bot_message(animate=False),
                add_event_divider=lambda text, animate=False: chat_view.add_event_divider(text, animate=False),
                get_user_messages=chat_view.get_user_messages,
                refresh_status_footer=MagicMock(),
                notify=MagicMock(),
                save_session=AsyncMock(),
            )

            async def _fake_stream(*args, **kwargs):
                yield ("tool", "read", "test.py", {"path": "test.py"})
                await asyncio.sleep(0.01)
                yield ("tool_result", "content of file\n" * 50, "", False, "done", 0)
                await asyncio.sleep(0.01)
                yield ("bot_delta", "Tool output analyzed.", "", None)

            agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
            agent.stream_steps = _fake_stream

            session = _create_fake_session()

            async def _run_stream():
                await generate_ai_response(
                    agent,
                    session,
                    canvas,
                    session_id="test_latency_session",
                    user_text="read test.py",
                    show_in_ui=True,
                )

            _, lag = await measure_event_loop_lag(_run_stream)
            self.assertLess(
                lag,
                self.MAX_ALLOWED_LAG_SECONDS,
                f"Tool stream pipeline froze UI for {lag * 1000:.1f}ms",
            )

    async def test_execute_tool_responsiveness(self):
        """Tool execution via registry must not block the event loop for prolonged duration."""
        async def _exec():
            return await execute_tool("read", {"path": "pyproject.toml"})

        result, lag = await measure_event_loop_lag(_exec)
        self.assertIsNotNone(result)
        self.assertLess(
            lag,
            self.MAX_ALLOWED_LAG_SECONDS,
            f"execute_tool('read') blocked loop for {lag * 1000:.1f}ms",
        )
