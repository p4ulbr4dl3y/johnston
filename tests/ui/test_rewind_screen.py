import unittest

from widgets.screens.rewind import RewindScreen


class TestRewindScreen(unittest.TestCase):
    def test_rewind_multiline_formatting(self):
        user_messages = [
            (0, "@/Users/yegor/testing/interactive_test.sh\nне чита..."),
            (1, "line 1\r\nline 2\r\nline 3"),
        ]
        screen = RewindScreen(user_messages)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("\n", screen.raw_options[0])
        self.assertNotIn("\r", screen.raw_options[0])
        self.assertIn("@/Users/yegor/testing/", screen.raw_options[0])
        self.assertNotIn("\n", screen.raw_options[1])
        self.assertIn("line 1 line 2 line 3", screen.raw_options[1])

    def test_checkpoints_disabled(self):
        user_messages = [(0, "hello world", "no checkpoint"), (1, "second message", "+5 / -2")]
        screen_enabled = RewindScreen(user_messages, checkpoints_enabled=True)
        self.assertIn("[no checkpoint]", screen_enabled.raw_options[0])
        self.assertIn("[+5 / -2]", screen_enabled.raw_options[1])

        screen_disabled = RewindScreen(user_messages, checkpoints_enabled=False)
        self.assertNotIn("[no checkpoint]", screen_disabled.raw_options[0])
        self.assertNotIn("[+5 / -2]", screen_disabled.raw_options[1])
        self.assertEqual(screen_disabled.raw_options[0], "hello world")
        self.assertEqual(screen_disabled.raw_options[1], "second message")
