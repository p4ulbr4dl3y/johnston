"""The command popup must not dim its description column (AA follow-up).

`[dim]` measured 3.35:1 (zinc) and 3.33:1 (github-light) against the popup
surface — the only text left below AA in the app. The row now keeps its own
colour (`$fg-secondary`, covered by `test_ui_theme_contrast.py`) and the
command name carries the emphasis instead.
"""

import pytest
from textual.containers import Vertical
from textual.screen import Screen

from app import JohnstonApp
from widgets.command_suggestions import CommandSuggestions


class PopupScreen(Screen):
    def compose(self):
        with Vertical():
            yield CommandSuggestions(id="cs")


def _prompts(widget: CommandSuggestions) -> list[str]:
    return [str(option.prompt) for option in widget.options]


@pytest.mark.asyncio
async def test_command_rows_are_not_dimmed():
    async with JohnstonApp().run_test(size=(100, 26)) as pilot:
        await pilot.pause(0.5)
        app = pilot.app
        app.push_screen(PopupScreen())
        await pilot.pause(0.5)
        cs = app.screen.query_one("#cs", CommandSuggestions)
        await cs.update_query("/")
        await pilot.pause(0.5)

        prompts = _prompts(cs)
        assert prompts, "no command suggestions rendered"
        for prompt in prompts:
            assert "[dim]" not in prompt, prompt


@pytest.mark.asyncio
async def test_command_name_keeps_the_emphasis():
    async with JohnstonApp().run_test(size=(100, 26)) as pilot:
        await pilot.pause(0.5)
        app = pilot.app
        app.push_screen(PopupScreen())
        await pilot.pause(0.5)
        cs = app.screen.query_one("#cs", CommandSuggestions)
        await cs.update_query("/help")
        await pilot.pause(0.5)

        prompts = _prompts(cs)
        assert prompts
        assert all(prompt.startswith("[bold]") for prompt in prompts), prompts
        # The description is still there, just not dimmed.
        assert "help and keybindings" in " ".join(prompts).lower()


@pytest.mark.asyncio
async def test_file_rows_are_not_dimmed():
    async with JohnstonApp().run_test(size=(100, 26)) as pilot:
        await pilot.pause(0.5)
        app = pilot.app
        app.push_screen(PopupScreen())
        await pilot.pause(0.5)
        cs = app.screen.query_one("#cs", CommandSuggestions)
        cs._cached_files = ["widgets/app/app.py", "docs/ui-audit/"]
        cs._cached_cwd = "sentinel"
        cs._cache_time = 1e18
        await cs.update_query("@app")
        await pilot.pause(0.5)

        prompts = _prompts(cs)
        assert prompts, "no file suggestions rendered"
        for prompt in prompts:
            assert "[dim]" not in prompt, prompt
        assert any("File" in prompt for prompt in prompts)
        assert any("Dir" in prompt for prompt in prompts)
