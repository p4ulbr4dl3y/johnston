"""Feedback while a response is streaming, and empty list states (P1-9).

Interrupting with `esc` was documented in /help but never surfaced during
generation, there was no elapsed timer, and `/subagents` / `/shell` replied
with a toast instead of opening their screen.
"""

import re

import pytest

ELAPSED_RE = re.compile(r"(\d+\.\d)s")


@pytest.mark.asyncio
async def test_footer_shows_interrupt_hint_and_timer_while_generating():
    from app import JohnstonApp
    from widgets.status_footer import StatusFooter

    app = JohnstonApp()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.3)
        footer = app.query_one(StatusFooter)

        assert "esc: interrupt" not in str(footer.content)

        footer.set_generating(True)
        await pilot.pause(0.3)
        content = str(footer.content)
        assert "esc: interrupt" in content, content
        assert ELAPSED_RE.search(content), content

        footer.set_generating(False)
        await pilot.pause(0.2)
        assert "esc: interrupt" not in str(footer.content)


@pytest.mark.asyncio
async def test_interrupt_timer_counts_up():
    from app import JohnstonApp
    from widgets.status_footer import StatusFooter

    app = JohnstonApp()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.3)
        footer = app.query_one(StatusFooter)
        footer.set_generating(True)
        await pilot.pause(0.2)
        first = float(ELAPSED_RE.search(str(footer.content)).group(1))
        await pilot.pause(1.1)
        second = float(ELAPSED_RE.search(str(footer.content)).group(1))
        assert second > first, (first, second)
        assert 0.9 <= second - first <= 1.6
        # The spinner redraw must not freeze the timer: it is redrawn per frame.
        assert footer._spinner_idx >= 0


@pytest.mark.asyncio
async def test_interrupt_hint_survives_a_spinner_frame():
    """`_render_stream_frame` rebuilds rows from cache; the live cell must be
    refreshed too, not replayed from the cache."""
    from app import JohnstonApp
    from widgets.status_footer import StatusFooter

    app = JohnstonApp()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.3)
        footer = app.query_one(StatusFooter)
        footer.set_generating(True)
        await pilot.pause(0.5)
        footer._spinner_idx = 7
        footer._render_stream_frame()
        assert "esc: interrupt" in str(footer.content)
        assert ELAPSED_RE.search(str(footer.content))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("screen_cls", "expected"),
    [
        ("SubagentsScreen", "No subagents yet."),
        ("ShellTasksScreen", "No background shell tasks."),
    ],
    ids=["subagents", "shell"],
)
async def test_empty_task_screens_render_an_empty_state(screen_cls, expected):
    import importlib

    from app import JohnstonApp

    screen_type = getattr(importlib.import_module("widgets.presentation.screens.tasks"), screen_cls)

    app = JohnstonApp()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.3)
        screen = screen_type()
        app.push_screen(screen)
        await pilot.pause(0.5)

        # The old behaviour dismissed the screen (or never opened it at all).
        assert screen.is_mounted, f"{screen_cls} closed itself on an empty list"
        opt_list = screen._get_option_list()
        rendered = "\n".join(str(option.prompt) for option in opt_list.options)
        assert expected in rendered, rendered
        assert all(option.disabled for option in opt_list.options)
