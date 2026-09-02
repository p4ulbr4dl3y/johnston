import unittest

from widgets.presentation.widgets.footer_layout import format_modal_hint, get_theme_colors
from widgets.presentation.widgets.modal_hint import ModalHint, ModalHintConfig


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

    def test_modal_hint_config_methods(self):
        cfg = ModalHintConfig(
            actions=[("enter", "select"), ("tab", "toggle")],
            close_key="esc",
            close_label="close",
        )
        self.assertEqual(cfg.actions_text(), "enter: select • tab: toggle")
        self.assertEqual(cfg.close_text(), "esc: close")
        self.assertEqual(cfg.to_hint_string(), "enter: select • tab: toggle • esc: close")

        formatted_actions = cfg.format_actions()
        self.assertIn("enter", formatted_actions)
        self.assertIn("select", formatted_actions)

        formatted_close = cfg.format_close()
        self.assertIn("esc", formatted_close)
        self.assertIn("close", formatted_close)

    def test_modal_hint_config_widget(self):
        cfg = ModalHintConfig(actions=[("enter", "confirm")], close_key="esc", close_label="cancel")
        widget = ModalHint(cfg)
        rendered = str(widget.render())
        self.assertIn("enter", rendered)
        self.assertIn("confirm", rendered)
        self.assertIn("esc", rendered)
        self.assertIn("cancel", rendered)

        new_cfg = ModalHintConfig(actions=[("space", "pause")])
        widget.update(new_cfg)
        rendered_after = str(widget.render())
        self.assertIn("space", rendered_after)
        self.assertIn("pause", rendered_after)

    def test_modal_hint_right_text(self):
        from rich.table import Table

        widget = ModalHint("enter: select • esc: close", right_text="5/42")
        rendered = widget.render()
        self.assertIsInstance(rendered, Table)
        self.assertEqual(len(rendered.columns), 2)

        widget.update("enter: select", right_text="10/100")
        rendered2 = widget.render()
        self.assertIsInstance(rendered2, Table)
        self.assertEqual(widget.right_text, "10/100")


if __name__ == "__main__":
    unittest.main()

