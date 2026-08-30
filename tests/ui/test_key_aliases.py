import unittest

from widgets.utils.key_aliases import (
    KEY_CUT,
    KEY_DETACH,
    KEY_NEWLINE,
    KEY_PASTE,
    KEY_QUIT,
    KEY_TOGGLE_DISABLED,
    KEY_TOGGLE_MODE,
    KEY_TOGGLE_ROLE,
    QWERTY_TO_AR,
    QWERTY_TO_EL,
    QWERTY_TO_HE,
    QWERTY_TO_HY,
    QWERTY_TO_KA,
    QWERTY_TO_RU,
    QWERTY_TO_SR,
    QWERTY_TO_UA_BY,
    expand_bindings,
    get_key_aliases,
    normalize_key_to_latin,
)


class TestKeyAliases(unittest.TestCase):
    def test_qwerty_mappings(self):
        self.assertIn("q", QWERTY_TO_RU)
        self.assertEqual(QWERTY_TO_RU["q"], "й")
        self.assertIn("s", QWERTY_TO_UA_BY)
        self.assertEqual(QWERTY_TO_UA_BY["s"], "і")
        self.assertIn("q", QWERTY_TO_SR)
        self.assertEqual(QWERTY_TO_SR["q"], "љ")
        self.assertIn("q", QWERTY_TO_EL)
        self.assertEqual(QWERTY_TO_EL["q"], ";")
        self.assertIn("e", QWERTY_TO_HE)
        self.assertEqual(QWERTY_TO_HE["e"], "ק")
        self.assertIn("q", QWERTY_TO_AR)
        self.assertEqual(QWERTY_TO_AR["q"], "ض")
        self.assertIn("q", QWERTY_TO_KA)
        self.assertEqual(QWERTY_TO_KA["q"], "ქ")
        self.assertIn("q", QWERTY_TO_HY)
        self.assertEqual(QWERTY_TO_HY["q"], "ք")

    def test_normalize_key_to_latin(self):
        self.assertEqual(normalize_key_to_latin(None), "")
        self.assertEqual(normalize_key_to_latin(""), "")
        self.assertEqual(normalize_key_to_latin("ctrl+c"), "ctrl+c")
        self.assertEqual(normalize_key_to_latin("ctrl+с"), "ctrl+c")
        self.assertEqual(normalize_key_to_latin("CTRL+С"), "ctrl+c")
        self.assertEqual(normalize_key_to_latin("ctrl+ב"), "ctrl+c")  # Hebrew
        self.assertEqual(normalize_key_to_latin("ctrl+ψ"), "ctrl+c")  # Greek
        self.assertEqual(normalize_key_to_latin("ctrl+ؤ"), "ctrl+c")  # Arabic
        self.assertEqual(normalize_key_to_latin("ctrl+ც"), "ctrl+c")  # Georgian
        self.assertEqual(normalize_key_to_latin("ctrl+ց"), "ctrl+c")  # Armenian
        self.assertEqual(normalize_key_to_latin("л"), "k")
        self.assertEqual(normalize_key_to_latin("escape"), "escape")
        self.assertEqual(normalize_key_to_latin("shift+tab"), "shift+tab")

    def test_get_key_aliases_ctrl_combinations(self):
        # Ctrl+C
        aliases_c = get_key_aliases("ctrl+c")
        self.assertIn("ctrl+c", aliases_c)
        self.assertIn("ctrl+с", aliases_c)  # Cyrillic RU
        self.assertIn("ctrl+С", aliases_c)
        self.assertIn("ctrl+ψ", aliases_c)  # Greek
        self.assertIn("ctrl+ב", aliases_c)  # Hebrew
        self.assertIn("ctrl+ؤ", aliases_c)  # Arabic
        self.assertIn("ctrl+ც", aliases_c)  # Georgian
        self.assertIn("ctrl+ց", aliases_c)  # Armenian

        # Ctrl+B
        aliases_b = get_key_aliases("ctrl+b")
        self.assertIn("ctrl+b", aliases_b)
        self.assertIn("ctrl+и", aliases_b)
        self.assertIn("ctrl+И", aliases_b)
        self.assertIn("ctrl+β", aliases_b)  # Greek
        self.assertIn("ctrl+נ", aliases_b)  # Hebrew

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
        self.assertIn("κ", aliases_k)
        self.assertIn("ל", aliases_k)
        self.assertIn("ن", aliases_k)

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

        # Checks that multi-layout aliases are added
        self.assertIn("ctrl+с", keys)
        self.assertIn("ctrl+С", keys)
        self.assertIn("ctrl+ψ", keys)
        self.assertIn("ctrl+ב", keys)
        self.assertIn("л", keys)
        self.assertIn("Л", keys)
        self.assertIn("κ", keys)
        self.assertIn("ל", keys)

        # Checks actions match
        c_action = [b[1] for b in expanded if b[0] == "ctrl+с"][0]
        self.assertEqual(c_action, "quit")
        greek_action = [b[1] for b in expanded if b[0] == "ctrl+ψ"][0]
        self.assertEqual(greek_action, "quit")

    def test_key_constants(self):
        self.assertTrue(len(KEY_QUIT) > 0)
        self.assertTrue(len(KEY_CUT) > 0)
        self.assertTrue(len(KEY_PASTE) > 0)
        self.assertTrue(len(KEY_DETACH) > 0)
        self.assertTrue(len(KEY_TOGGLE_ROLE) > 0)
        self.assertTrue(len(KEY_TOGGLE_MODE) > 0)
        self.assertTrue(len(KEY_NEWLINE) > 0)
        self.assertTrue(len(KEY_TOGGLE_DISABLED) > 0)
        self.assertIn("ctrl+с", KEY_QUIT)
        self.assertIn("ctrl+ב", KEY_QUIT)
        self.assertIn("ctrl+ψ", KEY_QUIT)
