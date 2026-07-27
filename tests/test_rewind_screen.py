import unittest

from widgets.screens.rewind import RewindScreen


class TestRewindScreen(unittest.TestCase):
    def test_rewind_multiline_formatting(self):
        user_messages = [
            (0, "@/Users/yegor/testing/interactive_test.sh\nне чита..."),
            (1, "line 1\r\nline 2\r\nline 3")
        ]
        screen = RewindScreen(user_messages)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("\n", screen.raw_options[0])
        self.assertNotIn("\r", screen.raw_options[0])
        self.assertIn("@/Users/yegor/testing/interactive_test.sh", screen.raw_options[0])
        self.assertNotIn("\n", screen.raw_options[1])
        self.assertEqual(screen.raw_options[1], "line 1 line 2 line 3  [no checkpoint]")
