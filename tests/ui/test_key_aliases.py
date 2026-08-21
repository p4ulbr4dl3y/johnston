import unittest

from widgets.utils.key_aliases import (
    KEY_BACKGROUND_ALL,
    KEY_DETACH,
    KEY_NEWLINE,
    KEY_PASTE,
    KEY_QUIT,
    KEY_TOGGLE_DISABLED,
    KEY_TOGGLE_EXPAND,
    KEY_TOGGLE_ROLE,
    QWERTY_TO_RU,
    RU_TO_QWERTY,
    expand_bindings,
    get_key_aliases,
)


class TestKeyAliases(unittest.TestCase):
    def test_qwerty_ru_bijective_mapping(self):
        self.assertEqual(len(QWERTY_TO_RU), len(RU_TO_QWERTY))
        for latin, ru in QWERTY_TO_RU.items():
            self.assertEqual(RU_TO_QWERTY[ru], latin)

    def test_get_key_aliases_ctrl_combinations(self):
        # Ctrl+C
        aliases_c = get_key_aliases("ctrl+c")
        self.assertIn("ctrl+c", aliases_c)
        self.assertIn("ctrl+с", aliases_c)
        self.assertIn("ctrl+С", aliases_c)

        # Ctrl+B
        aliases_b = get_key_aliases("ctrl+b")
        self.assertIn("ctrl+b", aliases_b)
        self.assertIn("ctrl+и", aliases_b)
        self.assertIn("ctrl+И", aliases_b)

        # Ctrl+O
        aliases_o = get_key_aliases("ctrl+o")
        self.assertIn("ctrl+o", aliases_o)
        self.assertIn("ctrl+щ", aliases_o)
        self.assertIn("ctrl+Щ", aliases_o)

        # Ctrl+V
        aliases_v = get_key_aliases("ctrl+v")
        self.assertIn("ctrl+v", aliases_v)
        self.assertIn("cmd+v", aliases_v)
        self.assertIn("ctrl+м", aliases_v)
        self.assertIn("ctrl+М", aliases_v)

        # Ctrl+D
        aliases_d = get_key_aliases("ctrl+d")
        self.assertIn("ctrl+d", aliases_d)
        self.assertIn("cmd+d", aliases_d)
        self.assertIn("ctrl+в", aliases_d)
        self.assertIn("ctrl+В", aliases_d)

        # Ctrl+T
        aliases_t = get_key_aliases("ctrl+t")
        self.assertIn("ctrl+t", aliases_t)
        self.assertIn("ctrl_t", aliases_t)
        self.assertIn("ctrl+i", aliases_t)
        self.assertIn("ctrl+е", aliases_t)
        self.assertIn("ctrl+Е", aliases_t)

    def test_get_key_aliases_tabs_and_newlines(self):
        # Shift+Tab
        aliases_tab = get_key_aliases("shift+tab")
        self.assertIn("shift+tab", aliases_tab)
        self.assertIn("backtab", aliases_tab)
        self.assertIn("shift_tab", aliases_tab)

        # Ctrl+Enter
        aliases_nl = get_key_aliases("ctrl+enter")
        self.assertIn("ctrl+enter", aliases_nl)
        self.assertIn("ctrl+j", aliases_nl)
        self.assertIn("shift+enter", aliases_nl)

    def test_get_key_aliases_single_char(self):
        aliases_k = get_key_aliases("k")
        self.assertIn("k", aliases_k)
        self.assertIn("л", aliases_k)
        self.assertIn("Л", aliases_k)

        aliases_esc = get_key_aliases("escape")
        self.assertEqual(aliases_esc, ("escape",))

    def test_expand_bindings(self):
        original = [
            ("ctrl+c", "quit", "Exit"),
            ("escape", "cancel", "Cancel"),
            ("k", "kill_task", "Kill Task"),
        ]
        expanded = expand_bindings(original)
        keys = [b[0] for b in expanded]

        # Checks that original keys and descriptions exist
        self.assertIn("ctrl+c", keys)
        self.assertIn("escape", keys)
        self.assertIn("k", keys)

        # Checks that layout aliases are added
        self.assertIn("ctrl+с", keys)
        self.assertIn("ctrl+С", keys)
        self.assertIn("л", keys)
        self.assertIn("Л", keys)

        # Checks actions match
        c_action = [b[1] for b in expanded if b[0] == "ctrl+с"][0]
        self.assertEqual(c_action, "quit")

    def test_key_constants(self):
        self.assertTrue(len(KEY_QUIT) > 0)
        self.assertTrue(len(KEY_PASTE) > 0)
        self.assertTrue(len(KEY_DETACH) > 0)
        self.assertTrue(len(KEY_BACKGROUND_ALL) > 0)
        self.assertTrue(len(KEY_TOGGLE_EXPAND) > 0)
        self.assertTrue(len(KEY_TOGGLE_ROLE) > 0)
        self.assertTrue(len(KEY_NEWLINE) > 0)
        self.assertTrue(len(KEY_TOGGLE_DISABLED) > 0)
