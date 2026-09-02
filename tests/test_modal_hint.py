import unittest

from widgets.presentation.widgets.footer_layout import format_hint, get_theme_colors
from widgets.presentation.widgets.modal_hint import ModalHint, ModalHintConfig


class TestModalHintFormatting(unittest.TestCase):
    def test_format_empty_or_none(self):
        self.assertEqual(format_hint(""), "")
        self.assertEqual(format_hint(None), "")

    def test_format_space_separated_hints(self):
        _, t_sec, t_mut, _ = get_theme_colors()
        raw = "↑/↓ Navigate • enter Select • tab Complete • esc Close"
        formatted = format_hint(raw)
        self.assertIn(f"[{t_sec}]↑/↓[/]", formatted)
        self.assertIn(f"[{t_mut}]Navigate[/]", formatted)
        self.assertIn(f"[{t_sec}]enter[/]", formatted)
        self.assertIn(f"[{t_mut}]Select[/]", formatted)
        self.assertIn(f"[{t_sec}]tab[/]", formatted)
        self.assertIn(f"[{t_mut}]Complete[/]", formatted)
        self.assertIn(f"[{t_sec}]esc[/]", formatted)
        self.assertIn(f"[{t_mut}]Close[/]", formatted)
        self.assertIn(f"[{t_mut}]•[/]", formatted)

    def test_format_colon_hints(self):
        _, t_sec, t_mut, _ = get_theme_colors()
        raw = "enter: select • esc: close"
        formatted = format_hint(raw)
        self.assertIn(f"[{t_sec}]enter[/]", formatted)
        self.assertIn(f"[{t_mut}]: select[/]", formatted)
        self.assertIn(f"[{t_mut}]•[/]", formatted)
        self.assertIn(f"[{t_sec}]esc[/]", formatted)
        self.assertIn(f"[{t_mut}]: close[/]", formatted)

    def test_format_compact_hints_without_colons(self):
        _, t_sec, t_mut, _ = get_theme_colors()
        raw = "enter • ↑↓ • esc"
        formatted = format_hint(raw)
        self.assertIn(f"[{t_sec}]enter[/]", formatted)
        self.assertIn(f"[{t_sec}]↑↓[/]", formatted)
        self.assertIn(f"[{t_sec}]esc[/]", formatted)
        self.assertIn(f"[{t_mut}]•[/]", formatted)

    def test_format_preserves_existing_markup(self):
        raw = "[#ffffff]custom[/] [#71717a]hint[/]"
        self.assertEqual(format_hint(raw), raw)

    def test_modal_hint_config_methods(self):
        cfg = ModalHintConfig(
            actions=[("enter", "Select"), ("tab", "Toggle")],
            close_key="esc",
            close_label="Close",
        )
        self.assertEqual(cfg.actions_text(), "enter Select • tab Toggle")
        self.assertEqual(cfg.close_text(), "esc Close")
        self.assertEqual(cfg.to_hint_string(), "enter Select • tab Toggle • esc Close")

        formatted_actions = cfg.format_actions()
        self.assertIn("enter", formatted_actions)
        self.assertIn("Select", formatted_actions)

        formatted_close = cfg.format_close()
        self.assertIn("esc", formatted_close)
        self.assertIn("Close", formatted_close)

    def test_modal_hint_config_widget(self):
        cfg = ModalHintConfig(actions=[("enter", "Confirm")], close_key="esc", close_label="Cancel")
        widget = ModalHint(cfg)
        rendered = str(widget.render())
        self.assertIn("enter", rendered)
        self.assertIn("Confirm", rendered)
        self.assertIn("esc", rendered)
        self.assertIn("Cancel", rendered)

        new_cfg = ModalHintConfig(actions=[("space", "Pause")])
        widget.update(new_cfg)
        rendered_after = str(widget.render())
        self.assertIn("space", rendered_after)
        self.assertIn("Pause", rendered_after)

    def test_modal_hint_right_text(self):
        from rich.table import Table

        widget = ModalHint("enter Select • esc Close", right_text="5/42")
        rendered = widget.render()
        self.assertIsInstance(rendered, Table)
        self.assertEqual(len(rendered.columns), 2)

        widget.update("enter Select", right_text="10/100")
        rendered2 = widget.render()
        self.assertIsInstance(rendered2, Table)
        self.assertEqual(widget.right_text, "10/100")


if __name__ == "__main__":
    unittest.main()

