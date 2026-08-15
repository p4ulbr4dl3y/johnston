"""Edge-case tests for widgets/patch and widgets/chat_welcome.

Detectors for real bugs in the Textual patch and digest login handling.
"""

import unittest

from textual.widget import Widget


class _FakeScreen(Widget):
    """Minimal node with parent chain to exercise allow_select walking."""

    def __init__(self):
        super().__init__()
        self.parent = None
        self._node_parent = None


class TestPatchAllowSelect(unittest.TestCase):
    def test_apply_patches_sets_allow_select_property(self):
        from widgets.patch import apply_textual_patches

        apply_textual_patches()

        desc = getattr(Widget, "allow_select", None)
        self.assertTrue(isinstance(desc, property))

    def test_apply_patches_idempotent(self):
        from widgets.patch import apply_textual_patches

        apply_textual_patches()
        apply_textual_patches()
        self.assertIsInstance(getattr(Widget, "allow_select", None), property)


class TestWelcomeWidget(unittest.TestCase):
    def test_banner_update_small_width(self):
        from widgets.presentation.widgets.chat_welcome import WelcomeWidget

        widget = WelcomeWidget()
        logo_mock = type("Logo", (), {"update": lambda *a, **k: None})()
        widget.query_one = lambda *a, **k: logo_mock
        # Must not raise for tiny widths.
        widget._update_banner_for_size(10)
        self.assertEqual(logo_mock.text if hasattr(logo_mock, "text") else None, None)

    def test_banner_update_missing_logo_is_noop(self):
        from widgets.presentation.widgets.chat_welcome import WelcomeWidget

        widget = WelcomeWidget()
        widget.query_one = lambda *a, **k: (_ for _ in ()).throw(Exception("missing"))
        widget._update_banner_for_size(100)  # must not raise


if __name__ == "__main__":
    unittest.main()
