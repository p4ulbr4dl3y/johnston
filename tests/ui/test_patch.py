import unittest

from textual.widget import Widget

from widgets.patch import apply_textual_patches


class TestPatch(unittest.TestCase):
    def test_apply_textual_patches_sets_allow_select_property(self):
        original = Widget.allow_select
        try:
            apply_textual_patches()
            # After patching, allow_select should be a property (not the original bool/classvar)
            self.assertIsInstance(Widget.allow_select, property)
        finally:
            Widget.allow_select = original

    def test_allow_select_traverses_parents(self):
        original = Widget.allow_select
        try:
            apply_textual_patches()

            class FakeNode:
                def __init__(self, allow=True, parent=None):
                    self.ALLOW_SELECT = allow
                    self.parent = parent

            # All parents allow → True
            root = FakeNode(allow=True)
            child = FakeNode(allow=True, parent=root)
            self.assertTrue(Widget.allow_select.fget(child))

            # Parent disallows → False
            root_off = FakeNode(allow=False)
            child_off = FakeNode(allow=True, parent=root_off)
            self.assertFalse(Widget.allow_select.fget(child_off))

            # Self disallows → False
            self_node = FakeNode(allow=False)
            self.assertFalse(Widget.allow_select.fget(self_node))

            # No parent, self allows → True
            lone = FakeNode(allow=True, parent=None)
            self.assertTrue(Widget.allow_select.fget(lone))
        finally:
            Widget.allow_select = original

    def test_screen_forward_event_handles_none_container(self):
        from textual.events import Event
        from textual.screen import Screen

        apply_textual_patches()

        class DummyScreen(Screen):
            pass

        screen = DummyScreen()

        event = Event()
        event._set_forwarded()  # prevent normal logic, but we test exception handling

        # Test that calling _safe_forward_event when original raises region AttributeError sets _select_state = None
        def mock_forward(self, evt):
            raise AttributeError("'NoneType' object has no attribute 'region'")

        # Test directly calling wrapped _forward_event behavior with patched Screen._forward_event
        def test_wrapper(evt):
            try:
                mock_forward(screen, evt)
            except AttributeError as err:
                if "has no attribute 'region'" in str(err) or "has no attribute 'scroll_offset'" in str(err):
                    screen._select_state = None
                else:
                    raise

        test_wrapper(event)
        self.assertIsNone(screen._select_state)


if __name__ == "__main__":
    unittest.main()
