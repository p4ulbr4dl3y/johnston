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


if __name__ == "__main__":
    unittest.main()
