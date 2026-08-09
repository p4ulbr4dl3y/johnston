import unittest

from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions


class TestFileSuggestions(unittest.TestCase):
    def test_file_suggestions_query(self):
        suggestions = CommandSuggestions()

        # 1. Typing '@' should enable 'file' mode and show files
        res = suggestions.update_query("@", "@", 1)
        self.assertEqual(suggestions.mode, "file")
        self.assertTrue(len(res) > 0)
        self.assertTrue(suggestions.display)
        self.assertIn("app.py", res)

        # 2. Filtering by file name (e.g. '@app')
        res_app = suggestions.update_query("Check @app", "Check @app", 10)
        self.assertEqual(suggestions.mode, "file")
        self.assertIn("app.py", res_app)

        # 3. Ignoring email addresses (char before @ is not space nor start of line)
        suggestions.update_query("test@domain.com", "test@domain.com", 15)
        self.assertIsNone(suggestions.mode)
        self.assertFalse(suggestions.display)

    def test_pasted_file_path_formatting(self):
        chat_input = ChatInput()
        pasted_img_path = "/var/folders/lg/x662tzs55wj3rpcv4fry/T/test.png"
        formatted_img = chat_input.format_pasted_file_path(pasted_img_path)
        self.assertEqual(formatted_img, f"@{pasted_img_path} ")

        pasted_code_path = "/var/folders/lg/x662tzs55wj3rpcv4fry/T/script.py"
        formatted_code = chat_input.format_pasted_file_path(pasted_code_path)
        self.assertEqual(formatted_code, f"@{pasted_code_path} ")

        normal_text = "def hello():\n    return 1"
        self.assertEqual(chat_input.format_pasted_file_path(normal_text), normal_text)
        self.assertEqual(chat_input.format_pasted_file_path("Task"), "Task")

        # Test file:// URL scheme
        self.assertEqual(chat_input.format_pasted_file_path("file:///tmp/script.py"), "@/tmp/script.py ")

        # Test quoted file path
        self.assertEqual(chat_input.format_pasted_file_path("'/tmp/script.py'"), "@/tmp/script.py ")

        # Test escaped spaces
        self.assertEqual(chat_input.format_pasted_file_path("/tmp/my\\ folder/script.py"), "@/tmp/my folder/script.py ")

        # Test URL-encoded file scheme drag and drop
        self.assertEqual(
            chat_input.format_pasted_file_path("file:///tmp/my%20folder/script.py"), "@/tmp/my folder/script.py "
        )


if __name__ == "__main__":
    unittest.main()
