import os
import unittest

from tests.conftest import WindowsSafeTemporaryDirectory
from tools.edit import EditTool, MultiEditTool, apply_chunk_replacements


class TestEditToolAdvanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = WindowsSafeTemporaryDirectory()
        self.test_dir = self.temp_dir.name
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    def test_overlapping_chunks_raise_error(self):
        content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        raw_chunks = [
            {"old_str": "line 2", "new_str": "line TWO", "start_line": 2, "end_line": 4},
            {"old_str": "line 3", "new_str": "line THREE", "start_line": 3, "end_line": 5},
        ]
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(content, raw_chunks, "dummy.py")
        self.assertIn("ERR: range: replacement chunks", str(ctx.exception))
        self.assertIn("overlap", str(ctx.exception))

    def test_non_overlapping_chunks_success(self):
        content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        raw_chunks = [
            {"old_str": "line 2\n", "new_str": "line TWO\n", "start_line": 2, "end_line": 2},
            {"old_str": "line 4\n", "new_str": "line FOUR\n", "start_line": 4, "end_line": 4},
        ]
        new_content, diff = apply_chunk_replacements(content, raw_chunks, "dummy.py")
        self.assertIn("line TWO", new_content)
        self.assertIn("line FOUR", new_content)
        self.assertIn("-line 2", diff)
        self.assertIn("+line TWO", diff)

    def test_crlf_preservation(self):
        content = "first line\r\nsecond line\r\nthird line\r\n"
        raw_chunks = [
            {
                "old_str": "second line",
                "new_str": "2nd line",
                "start_line": 2,
                "end_line": 2,
            }
        ]
        new_content, _ = apply_chunk_replacements(content, raw_chunks, "dummy.py")
        self.assertEqual(new_content, "first line\r\n2nd line\r\nthird line\r\n")

    def test_curly_quotes_normalization(self):
        content = "print('hello world')\n"
        raw_chunks = [
            {
                "old_str": "print(‘hello world’)",
                "new_str": "print(‘hello universe’)",
            }
        ]
        new_content, _ = apply_chunk_replacements(content, raw_chunks, "dummy.py")
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

    async def test_multi_edit_tool_fallback_chunks(self):
        tool = MultiEditTool()
        file_path = os.path.join(self.test_dir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("a = 1\nb = 2\nc = 3\n")

        res = str(await tool.execute(
            {
                "path": file_path,
                "edits": [
                    {"old_str": "a = 1", "new_str": "a = 10"},
                    {"old_str": "c = 3", "new_str": "c = 30"},
                ],
            }
        ))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "a = 10\nb = 2\nc = 30\n")

    def test_empty_target_content_raises_error(self):
        content = "foo\nbar\n"
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(content, [{"old_str": "", "new_str": "baz"}], "dummy.py")
        self.assertIn("cannot be empty", str(ctx.exception))

    def test_deletion_of_block(self):
        content = "line 1\nline 2\nline 3\n"
        new_content, _ = apply_chunk_replacements(
            content, [{"old_str": "line 2\n", "new_str": ""}], "dummy.py"
        )
        self.assertEqual(new_content, "line 1\nline 3\n")

    def test_multiple_occurrences_raises_error(self):
        content = "dup\ndup\ndup\n"
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(content, [{"old_str": "dup", "new_str": "unique"}], "dummy.py")
        self.assertIn("matches 3 occurrences", str(ctx.exception))

    def test_out_of_bounds_start_line_raises_error(self):
        content = "line 1\nline 1\n"
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(
                content,
                [{"old_str": "line 1", "new_str": "X", "start_line": 99, "end_line": 100}],
                "dummy.py",
            )
        self.assertIn("exceeds file line count", str(ctx.exception))

    def test_fuzzy_hint_on_missing_target(self):
        content = "def calculate_total_price(items):\n    return sum(items)\n"
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(
                content,
                [{"old_str": "def calculate_total_price(item_list):", "new_str": "pass"}],
                "dummy.py",
            )
        self.assertIn("Nearest matching code", str(ctx.exception))
