"""Esc wording and declared-vs-advertised bindings (P2-11).

Esc was labelled three different ways for the same gesture, and the `space:
toggle` hint in /skills, /mcp and /providers pointed at a handler that no
BINDINGS entry declared — so the footer and /help could not see it.
"""

import pytest

from widgets.presentation.screens.constants import (
    ESC_HINT_BACK,
    ESC_HINT_CANCEL,
    ESC_HINT_CLOSE,
)


def test_esc_wording_constants():
    assert ESC_HINT_CLOSE == "esc: close"
    assert ESC_HINT_CANCEL == "esc: cancel"
    assert ESC_HINT_BACK == "esc: back"


def test_esc_hints_come_from_the_shared_constants():
    """No screen may hard-code its own esc wording — that is how the three
    variants drifted apart in the first place."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "widgets"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "constants.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if "esc: close" in line or "esc: cancel" in line or "esc: back" in line:
                offenders.append(f"{path.relative_to(root)}:{lineno}: {line.strip()[:70]}")
    assert not offenders, "hard-coded esc wording:\n" + "\n".join(offenders)


def test_space_toggle_bindings_are_declared():
    """The hint promises `space: toggle`; it must exist as a binding so the
    footer and /help can advertise it."""
    from widgets.presentation.screens.mcp import MCPScreen
    from widgets.presentation.screens.providers import ProvidersScreen
    from widgets.presentation.screens.skills import SkillsScreen

    for screen_cls in (SkillsScreen, MCPScreen, ProvidersScreen):
        keys = {binding[0] for binding in screen_cls.BINDINGS}
        assert "space" in keys, f"{screen_cls.__name__}: `space` is not a declared binding"
        assert screen_cls.space_actions, f"{screen_cls.__name__}: no space_actions to guard"


@pytest.mark.asyncio
async def test_space_typed_into_search_stays_a_space():
    """Declaring `space` must not eat spaces while the user types a query."""
    from unittest.mock import patch

    from app import JohnstonApp
    from core.application.skills.manager import get_skill_manager
    from widgets.presentation.screens.skills import SkillsScreen

    class FakeSkill:
        name = "alpha skill"

        def to_dict(self):
            return {"name": self.name, "hidden": False}

    app = JohnstonApp()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.3)
        with patch.object(
            get_skill_manager().__class__, "list_skills", return_value=[FakeSkill()]
        ), patch.object(get_skill_manager().__class__, "toggle_hidden", return_value=True) as toggle:
            screen = SkillsScreen()
            app.push_screen(screen)
            await pilot.pause(0.4)
            await pilot.press("a", "space", "b")
            await pilot.pause(0.2)

            assert screen.query_one("#modal-search-input").value == "a b"
            toggle.assert_not_called()


@pytest.mark.asyncio
async def test_space_toggles_when_the_list_has_focus():
    from unittest.mock import patch

    from app import JohnstonApp
    from core.application.skills.manager import get_skill_manager
    from widgets.presentation.screens.skills import SkillsScreen

    class FakeSkill:
        name = "alpha skill"

        def to_dict(self):
            return {"name": self.name, "hidden": False}

    app = JohnstonApp()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause(0.3)
        with patch.object(
            get_skill_manager().__class__, "list_skills", return_value=[FakeSkill()]
        ), patch.object(get_skill_manager().__class__, "toggle_hidden", return_value=True) as toggle:
            screen = SkillsScreen()
            app.push_screen(screen)
            await pilot.pause(0.4)
            toggle.reset_mock()
            # With the search box focused a space belongs to the query, so the
            # toggle only fires once focus is on the list.
            screen.query_one("#skills-option-list").focus()
            await pilot.pause(0.1)
            await pilot.press("space")
            await pilot.pause(0.2)
            toggle.assert_called_once()
