import unittest

from widgets.presentation.widgets.footer_layout import format_modal_hint, get_theme_colors
from widgets.presentation.widgets.modal_hint import ModalHint


class TestModalHintFormatting(unittest.TestCase):
    def test_format_empty_or_none(self):
        self.assertEqual(format_modal_hint(""), "")
        self.assertEqual(format_modal_hint(None), "")

    def test_format_colon_hints(self):
        _, t_sec, t_mut, _ = get_theme_colors()
        raw = "enter: select • esc: close"
        formatted = format_modal_hint(raw)
        self.assertIn(f"[{t_sec}]enter[/]", formatted)
        self.assertIn(f"[{t_mut}]: select[/]", formatted)
        self.assertIn(f"[{t_mut}]•[/]", formatted)
        self.assertIn(f"[{t_sec}]esc[/]", formatted)
        self.assertIn(f"[{t_mut}]: close[/]", formatted)

    def test_format_compact_hints_without_colons(self):
        _, t_sec, t_mut, _ = get_theme_colors()
        raw = "enter • ↑↓ • esc"
        formatted = format_modal_hint(raw)
        self.assertIn(f"[{t_sec}]enter[/]", formatted)
        self.assertIn(f"[{t_sec}]↑↓[/]", formatted)
        self.assertIn(f"[{t_sec}]esc[/]", formatted)
        self.assertIn(f"[{t_mut}]•[/]", formatted)

    def test_format_preserves_existing_markup(self):
        raw = "[#ffffff]custom[/] [#71717a]hint[/]"
        self.assertEqual(format_modal_hint(raw), raw)

    def test_modal_hint_widget(self):
        widget = ModalHint("enter: save • esc: cancel")
        rendered = str(widget.render())
        self.assertIn("enter", rendered)
        self.assertIn("save", rendered)

        widget.update("enter • esc")
        rendered_after = str(widget.render())
        self.assertIn("enter", rendered_after)
        self.assertIn("esc", rendered_after)


if __name__ == "__main__":
    unittest.main()
