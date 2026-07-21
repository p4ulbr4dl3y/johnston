import unittest

from app import JohnstonChatApp
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions


class TestFileSuggestions(unittest.TestCase):

    def test_file_suggestions_query(self):
        suggestions = CommandSuggestions()

        # 1. Ввод '@' должен включить режим 'file' и показать файлы
        res = suggestions.update_query("@", "@", 1)
        self.assertEqual(suggestions.mode, "file")
        self.assertTrue(len(res) > 0)
        self.assertTrue(suggestions.display)
        self.assertIn("app.py", res)

        # 2. Фильтрация по имени файла (например '@app')
        res_app = suggestions.update_query("Check @app", "Check @app", 10)
        self.assertEqual(suggestions.mode, "file")
        self.assertIn("app.py", res_app)

        # 3. Игнорирование email адресов (символ перед @ не пробел и не начало строки)
        suggestions.update_query("test@domain.com", "test@domain.com", 15)
        self.assertIsNone(suggestions.mode)
        self.assertFalse(suggestions.display)

    def test_prepare_prompt_with_attachments(self):
        app = JohnstonChatApp()

        # Если прикреплен существующий файл (например @AGENTS.md)
        prompt = app.prepare_prompt_with_attachments("Check @AGENTS.md and fix")
        self.assertIn("Check @AGENTS.md and fix", prompt)
        self.assertIn("--- Attached File: AGENTS.md ---", prompt)
        self.assertIn("AI Agents and Providers in Johnston Chat", prompt)

    def test_pasted_file_path_formatting(self):
        chat_input = ChatInput()
        pasted_img_path = "/var/folders/lg/x662tzs55wj3rpcv4fry/T/test.png"
        formatted_img = chat_input.format_pasted_file_path(pasted_img_path)
        self.assertEqual(formatted_img, "[Image #1]")
        self.assertEqual(chat_input.pasted_texts["[Image #1]"], f"@{pasted_img_path}")

        pasted_code_path = "/var/folders/lg/x662tzs55wj3rpcv4fry/T/script.py"
        formatted_code = chat_input.format_pasted_file_path(pasted_code_path)
        self.assertEqual(formatted_code, f"@{pasted_code_path}")

        normal_text = "def hello():\n    return 1"
        self.assertEqual(chat_input.format_pasted_file_path(normal_text), normal_text)


if __name__ == "__main__":
    unittest.main()
