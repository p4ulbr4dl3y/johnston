import os
import unittest
from unittest import mock

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

    async def test_edit_tool_basic(self):
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
        res = apply_edit(content, "", "baz", False, "dummy.py")
        self.assertTrue(res.is_error)
        self.assertIn("cannot be empty", res.content)

    def test_same_old_and_new_str_raises_error(self):
        content = "foo\nbar\n"
        res = apply_edit(content, "foo", "foo", False, "dummy.py")
        self.assertTrue(res.is_error)
        self.assertIn("new_str must be different", res.content)

    def test_deletion_of_block(self):
        content = "line 1\nline 2\nline 3\n"
        new_content, _ = apply_edit(
            content, "line 2\n", "", False, "dummy.py"
        )
        self.assertEqual(new_content, "line 1\nline 3\n")

    def test_multiple_occurrences_raises_error(self):
        content = "dup\ndup\ndup\n"
        res = apply_edit(content, "dup", "unique", False, "dummy.py")
        self.assertTrue(res.is_error)
        self.assertIn("matches 3 occurrences", res.content)

    def test_fuzzy_hint_on_missing_target(self):
        content = "def calculate_total_price(items):\n    return sum(items)\n"
        res = apply_edit(
            content,
            "def calculate_total_price(item_list):",
            "pass",
            False,
            "dummy.py",
        )
        self.assertTrue(res.is_error)
        self.assertIn("Closest match", res.content)
        self.assertTrue("'dummy.py'" in res.content or "&apos;dummy.py&apos;" in res.content)

    def test_match_failure_returns_error_tool_result(self):
        res = apply_edit("foo\n", "bar", "baz", False, "dummy.py")
        self.assertTrue(res.is_error)
        self.assertTrue(res.content.startswith("ERR: match"))


    async def test_missing_new_str_key_means_delete(self):
        # Pinned behavior: an ABSENT new_str key deletes the target in one turn
        # (test_edit_missing_new_str_is_delete); only explicit "" vs missing
        # differ for providers that drop empty-string args.
        tool = EditTool()
        file_path = os.path.join(self.test_dir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("line1\ndrop\nline2\n")

        res = str(await tool.execute({"path": file_path, "old_str": "drop\n"}))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "line1\nline2\n")

    async def test_explicit_empty_new_str_still_deletes(self):
        # "" must stay a valid replacement (deletion).
        tool = EditTool()
        file_path = os.path.join(self.test_dir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("line1\ndrop\nline2\n")

        res = str(await tool.execute({"path": file_path, "old_str": "drop\n", "new_str": ""}))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "line1\nline2\n")

    async def test_unexpected_valueerror_wrapped_as_params(self):
        # A plain ValueError escaping apply_edit must wrap into a params error,
        # never leak raw text as a successful result.
        tool = EditTool()
        file_path = os.path.join(self.test_dir, "test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("x = 1\n")

        with mock.patch("tools.edit.apply_edit", side_effect=ValueError("boom")):
            res = str(await tool.execute({"path": file_path, "old_str": "x = 1", "new_str": "x = 2"}))
        self.assertIn("ERR: params", res)
        self.assertIn("boom", res)

    def test_whitespace_agnostic_match_recovers_indentation(self):
        content = "class Foo:\n    def bar(self):\n        return 42\n"
        # LLM provided unindented old_str and new_str
        old_str = "def bar(self):\n    return 42"
        new_str = "def bar(self):\n    return 100"
        new_content, _ = apply_edit(content, old_str, new_str, False, "test.py")
        self.assertEqual(new_content, "class Foo:\n    def bar(self):\n        return 100\n")

    def test_whitespace_agnostic_match_recovers_nested_indentation(self):
        content = "    if cond:\n        x = 1\n        y = 2\n"
        # LLM provided old_str with 0-indent and new_str with an extra inner level
        old_str = "if cond:\n    x = 1\n    y = 2"
        new_str = "if cond:\n    x = 1\n    if sub:\n        y = 2"
        new_content, _ = apply_edit(content, old_str, new_str, False, "test.py")
        self.assertEqual(new_content, "    if cond:\n        x = 1\n        if sub:\n            y = 2\n")

    def test_whitespace_agnostic_duplicate_match_returns_hint(self):
        content = "    x = 1\n    y = 2\n        x = 1\n        y = 2\n"
        # Non-unique whitespace match
        old_str = "x = 1\ny = 2"
        res = apply_edit(content, old_str, "x = 9\ny = 9", False, "test.py")
        self.assertTrue(res.is_error)
        self.assertIn("Closest match", res.content)
        self.assertTrue("'test.py'" in res.content or "&apos;test.py&apos;" in res.content)

