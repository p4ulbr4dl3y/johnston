import os
import unittest

from tests.conftest import WindowsSafeTemporaryDirectory
from tools.edit import EditTool, apply_edit


class TestEditToolAdvanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = WindowsSafeTemporaryDirectory()
        self.test_dir = self.temp_dir.name
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_crlf_preservation(self):
        content = "first line\r\nsecond line\r\nthird line\r\n"
        new_content, _ = apply_edit(content, "second line", "2nd line", False, "dummy.py")
        self.assertEqual(new_content, "first line\r\n2nd line\r\nthird line\r\n")

    def test_curly_quotes_normalization(self):
        content = "print('hello world')\n"
        new_content, _ = apply_edit(content, "print(‘hello world’)", "print(‘hello universe’)", False, "dummy.py")
        self.assertEqual(new_content, "print('hello universe')\n")

    async def test_edit_tool_fallback_keys(self):
        tool = EditTool()
        file_path = os.path.join(self.test_dir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def foo():\n    pass\n")

        res = str(await tool.execute({"path": file_path, "old_str": "def foo():", "new_str": "def bar():"}))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "def bar():\n    pass\n")

    async def test_edit_tool_replace_all(self):
        tool = EditTool()
        file_path = os.path.join(self.test_dir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("val = 1\nval = 1\nval = 1\n")

        res = str(await tool.execute({"path": file_path, "old_str": "val = 1", "new_str": "val = 2", "replace_all": True}))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "val = 2\nval = 2\nval = 2\n")

    def test_empty_target_content_raises_error(self):
        content = "foo\nbar\n"
        with self.assertRaises(ValueError) as ctx:
            apply_edit(content, "", "baz", False, "dummy.py")
        self.assertIn("cannot be empty", str(ctx.exception))

    def test_same_old_and_new_str_raises_error(self):
        content = "foo\nbar\n"
        with self.assertRaises(ValueError) as ctx:
            apply_edit(content, "foo", "foo", False, "dummy.py")
        self.assertIn("new_str must be different", str(ctx.exception))

    def test_deletion_of_block(self):
        content = "line 1\nline 2\nline 3\n"
        new_content, _ = apply_edit(
            content, "line 2\n", "", False, "dummy.py"
        )
        self.assertEqual(new_content, "line 1\nline 3\n")

    def test_multiple_occurrences_raises_error(self):
        content = "dup\ndup\ndup\n"
        with self.assertRaises(ValueError) as ctx:
            apply_edit(content, "dup", "unique", False, "dummy.py")
        self.assertIn("matches 3 occurrences", str(ctx.exception))

    def test_fuzzy_hint_on_missing_target(self):
        content = "def calculate_total_price(items):\n    return sum(items)\n"
        with self.assertRaises(ValueError) as ctx:
            apply_edit(
                content,
                "def calculate_total_price(item_list):",
                "pass",
                False,
                "dummy.py",
            )
        self.assertIn("Nearest matching code", str(ctx.exception))
