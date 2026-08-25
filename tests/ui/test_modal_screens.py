"""Coverage/exception-path tests for confirmation-style modal screens.

Covers widgets/presentation/screens/ask_user.py (wizard branches) and
widgets/presentation/screens/permission_confirm.py (message composition).
"""

import time
import unittest
from unittest.mock import MagicMock

from textual.app import App

from widgets.presentation.screens.ask_user import WRITE_IN_LABEL, AskUserWizardScreen


class _PermHostApp(App[None]):
    """Host app for mounting the permission confirm modal."""

    def __init__(self, screen):
        super().__init__()
        self._scr = screen

    def on_mount(self):
        self.push_screen(self._scr)


def _ask_screen(questions=(), q_idx=0, raw_options=None, options=None, answers=None):
    """Build a bare AskUserWizardScreen with minimal, safe state."""
    s = AskUserWizardScreen.__new__(AskUserWizardScreen)
    s.questions = list(questions)
    s.q_idx = q_idx
    s.raw_options = raw_options if raw_options is not None else []
    s.options = options if options is not None else []
    s.answers = answers if answers is not None else {}
    s._is_mounted = False
    return s


class TestAskUserExtra(unittest.IsolatedAsyncioTestCase):
    """Additional branches of ask_user.py complementing test_ask_user_screen.py."""

    async def test_force_modal_focus_not_mounted(self):
        screen = _ask_screen(questions=[{"question": "Q"}], raw_options=["A"])
        screen._force_modal_focus()  # is_mounted False -> early return

    async def test_force_modal_focus_query_exceptions(self):
        from widgets.presentation.screens.ask_user import WRITE_IN_INPUT

        screen = _ask_screen(questions=[{"question": "Q"}])
        screen._is_mounted = True

        def fake_qo(sel, cls):
            if sel == WRITE_IN_INPUT:
                raise Exception("no input")
            raise Exception("no opt")

        screen.query_one = fake_qo
        screen._force_modal_focus()  # raw_options empty -> input branch except
        screen.raw_options = ["A"]
        screen._force_modal_focus()  # raw_options set -> option-list branch except

    async def test_focus_options_and_first(self):
        screen = _ask_screen(raw_options=["A", "B"], options=["A", "B", WRITE_IN_LABEL])
        screen._is_mounted = True
        opt_list = MagicMock()
        input_field = MagicMock()
        screen.query_one = MagicMock(side_effect=lambda sel, cls: input_field if cls.__name__ == "Input" else opt_list)
        screen.focus_options_list()
        self.assertFalse(input_field.display)
        self.assertEqual(opt_list.highlighted, 1)
        screen.focus_first_option()
        self.assertEqual(opt_list.highlighted, 0)

        # exception paths
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.focus_options_list()
        screen.focus_first_option()

    async def test_focus_helpers_no_raw_options(self):
        screen = _ask_screen(raw_options=[])
        screen.focus_options_list()
        screen.focus_first_option()
        screen.focus_write_in_input = MagicMock()
        screen.on_option_list_option_highlighted(MagicMock())  # not mounted -> return 291

    async def test_update_step_write_in_tag_flows(self):
        screen = _ask_screen(
            [{"question": "Q1", "options": ["A", "B"]}],
            raw_options=["A", "B"],
            options=["A", "B", WRITE_IN_LABEL],
        )
        title = MagicMock()
        opt_list = MagicMock()
        opt_list.highlighted = 0
        input_field = MagicMock()

        def fake_qo(sel, cls):
            if cls.__name__ == "Markdown":
                return title
            if cls.__name__ == "OptionList":
                return opt_list
            return input_field  # Label or Input

        screen.query_one = MagicMock(side_effect=fake_qo)
        # prev answer is a write-in (208-210)
        screen.answers = {0: {"answer": "custom"}}
        screen.update_step()
        # prev answer is a raw option (204-206)
        screen.answers = {0: {"answer": "A"}}
        screen.update_step()
        # target_highlight = last (write-in) option with prev write-in answer (200)
        screen.answers = {0: {"answer": "custom"}}
        screen.update_step(target_highlight=2)
        # target_highlight within raw options (201-202)
        screen.answers = {}
        screen.update_step(target_highlight=1)
        # no prev answer -> first option (211-213)
        screen.answers = {}
        screen.update_step()
        self.assertEqual(opt_list.highlighted, 0)
        self.assertTrue(input_field.display is False)

    async def test_on_option_highlighted_and_selected(self):
        screen = _ask_screen(
            [{"question": "Q", "options": ["A", "B"]}],
            raw_options=["A", "B"],
            options=["A", "B", WRITE_IN_LABEL],
        )
        screen._is_mounted = True
        input_field = MagicMock()
        screen.query_one = MagicMock(side_effect=lambda sel, cls: input_field)
        evt = MagicMock()
        evt.option_index = 0
        screen.on_option_list_option_highlighted(evt)  # normal highlight of first option

        # last option selected -> focus write-in input (311)
        evt.option_index = 2
        screen.on_option_list_option_selected(evt)

        # exception path for highlighted (298-299)
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.on_option_list_option_highlighted(evt)

    async def test_selected_guards(self):
        # guard return: q_idx >= len(questions) (303)
        screen = _ask_screen([{"question": "Q"}], q_idx=1, raw_options=["A"], options=["A"])
        screen._is_mounted = True
        screen.query_one = MagicMock()
        screen.on_option_list_option_selected(MagicMock())
        # guard return: no raw_options (303)
        screen = _ask_screen([{"question": "Q"}], q_idx=0, raw_options=[], options=[])
        screen._is_mounted = True
        screen.query_one = MagicMock()
        screen.on_option_list_option_selected(MagicMock())

    async def test_selected_mount_time_and_input_submitted_guard(self):
        screen = _ask_screen([{"question": "Q"}], raw_options=["A"], options=["A"])
        screen._is_mounted = True
        screen.query_one = MagicMock(return_value=MagicMock())
        screen._mount_time = time.time()  # too recent -> 307 return
        screen.on_option_list_option_selected(MagicMock())
        screen.on_input_submitted(MagicMock())  # -> 317 return

    async def test_action_toggle_selection_branches(self):
        screen = _ask_screen([{"question": "Q", "options": ["A"]}], raw_options=["A"], options=["A"])
        # guard return: q_idx too high (349)
        screen.q_idx = 1
        screen.query_one = MagicMock()
        screen.action_toggle_selection()
        screen.q_idx = 0

        # option list not focused -> return (353)
        opt_list = MagicMock()
        opt_list.has_focus = False
        screen.query_one = MagicMock(return_value=opt_list)
        screen.action_toggle_selection()

        # exception path (363-364)
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.action_toggle_selection()

        # actual toggle with focused option list
        opt_list = MagicMock()
        opt_list.has_focus = True
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        screen.action_toggle_selection()
        self.assertIn(0, screen.answers)

    async def test_action_minimize(self):
        screen = _ask_screen(answers={0: {"answer": "A"}}, q_idx=1)
        result = []
        screen.dismiss = result.append
        screen.action_minimize()
        self.assertEqual(result, [{"action": "minimize", "answers": {0: {"answer": "A"}}, "q_idx": 1}])


class TestPermissionConfirmExtra(unittest.IsolatedAsyncioTestCase):
    def test_build_diff_text_unknown_tool(self):
        from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen

        screen = PermissionConfirmScreen("read", {"path": "x"})
        self.assertEqual(screen._build_diff_text("x"), "")

    async def test_compose_manage_subagent(self):
        from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen

        cases = [
            {"action": "kill", "session_id": "s1"},
            {"action": "kill"},
            {"action": "list"},
            {"action": "send_message", "session_id": "s1"},
            {"action": "send_message"},
            {"action": "manage", "session_id": "s1"},
        ]
        for args in cases:
            screen = PermissionConfirmScreen("manage_subagent", args)
            async with _PermHostApp(screen).run_test() as pilot:
                await pilot.pause()

    async def test_compose_update_plan(self):
        from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen

        screen = PermissionConfirmScreen("update_plan", {})
        async with _PermHostApp(screen).run_test() as pilot:
            await pilot.pause()

    async def test_compose_ask_user(self):
        from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen

        cases = [
            {"questions": [{"q": "1"}, {"q": "2"}]},
            {"questions": [{"q": "1"}]},
            {"questions": []},
        ]
        for args in cases:
            screen = PermissionConfirmScreen("ask_user", args)
            async with _PermHostApp(screen).run_test() as pilot:
                await pilot.pause()


class TestModalScreenBindings(unittest.TestCase):
    def test_mcp_bindings_include_quit(self):
        from widgets.presentation.screens.mcp import MCPScreen

        actions = {b[1] for b in MCPScreen.BINDINGS}
        self.assertIn("cancel", actions)
        self.assertIn("quit_app", actions)


if __name__ == "__main__":
    unittest.main()


