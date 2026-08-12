import unittest
from unittest.mock import patch

from widgets.screens.providers import ProvidersScreen
from widgets.screens.resume import ResumeScreen
from widgets.screens.rewind import RewindScreen


class TestResumeEdge(unittest.TestCase):
    def test_session_missing_id_uses_gettext(self):
        """Sessions without 'id' (malformed payload) must not raise KeyError."""
        try:
            s = ResumeScreen([{"title": "T", "message_count": 2}])
        except KeyError as exc:
            self.fail(f"missing id raised KeyError: {exc}")
        self.assertEqual(len(s.raw_items), 1)

    def test_empty_title_and_zero_count(self):
        s = ResumeScreen([{"id": "s1", "title": "", "message_count": 0}])
        self.assertEqual(len(s.raw_options), 1)


class TestRewindEdge(unittest.TestCase):
    def test_short_tuple_index_guard(self):
        """A 2-element message tuple is valid; a 1-element tuple (malformed)
        must not raise IndexError."""
        try:
            s = RewindScreen([(1,)])
        except IndexError as exc:
            self.fail(f"1-element tuple raised IndexError: {exc}")
        self.assertEqual(len(s.raw_items), 1)

    def test_empty_message_uses_placeholder(self):
        s = RewindScreen([(0, "")])
        self.assertIn("(empty message)", s.raw_options[0])


class TestProvidersEdge(unittest.TestCase):
    def test_provider_missing_key_uses_get(self):
        """Provider dicts missing 'key' (malformed payload) must not raise KeyError."""
        try:
            s = ProvidersScreen({"p1": {"name": "P1"}}, "p1", {})
        except KeyError as exc:
            self.fail(f"missing key raised KeyError: {exc}")
        self.assertEqual(s.raw_items, ["p1"])

    def test_provider_target_is_none_value(self):
        """A provider value that is None (malformed payload) must not raise
        AttributeError during option building."""
        try:
            s = ProvidersScreen({"p1": None}, "", {})
        except (KeyError, AttributeError, TypeError) as exc:
            self.fail(f"None provider value raised {type(exc).__name__}: {exc}")
        self.assertEqual(s.raw_items, [])


class TestConfirmCancelPath(unittest.TestCase):
    def test_confirm_cancel_dismisses_cancelled(self):
        from widgets.modal_screens import ConfirmScreen

        s = ConfirmScreen("summary")
        with patch.object(s, "dismiss") as dismiss:
            s._mount_time = 0  # old mount => bypass debounce
            s.action_cancel()
        dismiss.assert_called_once_with("cancelled")

    def test_confirm_enter_debounced_bypass(self):
        from widgets.modal_screens import ConfirmScreen

        s = ConfirmScreen("summary")
        with patch.object(s, "dismiss") as dismiss:
            s._mount_time = 0
            s.action_confirm()
        dismiss.assert_called_once_with("confirm")


if __name__ == "__main__":
    unittest.main()
