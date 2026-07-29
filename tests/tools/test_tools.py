import os
import tempfile
import unittest

from tools.create import CreateTool
from tools.edit import EditTool
from tools.linter import run_linter
from tools.read import ReadTool
from tools.shell import ShellTool


class MockAgent:
    def __init__(self, mode="explore"):
        self.mode = mode

class MockApp:
    def __init__(self, mode="explore"):
        self.agent = MockAgent(mode=mode)
        self.notified = []

    def notify(self, msg: str):
        self.notified.append(msg)

    def refresh_status_footer(self):
        pass


class TestTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    async def test_read_tool(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "sample.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")

        # Full read
        res = await tool.execute({"path": file_path})
        self.assertIn("Line 1", res)
        self.assertIn("Line 5", res)

        # Range read
        res_range = await tool.execute({"path": file_path, "start_line": 2, "end_line": 4})
        self.assertIn("Lines 2-4", res_range)
        self.assertIn("Line 2", res_range)
        self.assertNotIn("Line 5", res_range)

        # Non-existent file
        res_err = await tool.execute({"path": os.path.join(self.test_dir, "missing.txt")})
        self.assertIn("Error:", res_err)

        # Directory read (should auto-list directory contents)
        dir_res = await tool.execute({"path": self.test_dir})
        self.assertIn("is a directory", dir_res)
        self.assertIn("sample.txt", dir_res)

        # Plain text HTML file (read as raw text without markitdown)
        html_path = os.path.join(self.test_dir, "doc.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<h1>Test HTML</h1>")
        res_html = await tool.execute({"path": html_path})
        self.assertIn("<h1>Test HTML</h1>", res_html)

        # PDF document format via markitdown conversion
        pdf_path = os.path.join(self.test_dir, "doc.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.7 mock content")

        from unittest.mock import patch
        with patch("tools.read.convert_doc_to_markdown_sync", return_value="# Converted PDF Header\nPDF body text"):
            res_pdf = await tool.execute({"path": pdf_path})
            self.assertIn("Converted PDF Header", res_pdf)

    async def test_create_tool(self):
        tool = CreateTool()
        file_path = os.path.join(self.test_dir, "nested", "new_file.txt")

        # Create file in non-existent directory
        res = await tool.execute({"path": file_path, "content": "Hello World"})
        self.assertIn("Success: file", res)
        self.assertTrue(os.path.exists(file_path))
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Hello World")

    async def test_edit_tool(self):
        tool = EditTool()
        file_path = os.path.join(self.test_dir, "code.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def foo():\n    return 42\n")

        # Successful edit
        res = await tool.execute({
            "path": file_path,
            "old_string": "return 42",
            "new_string": "return 100"
        })
        self.assertIn("-    return 42", res)
        self.assertIn("+    return 100", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "def foo():\n    return 100\n")

        # Old string not found error
        res_not_found = await tool.execute({
            "path": file_path,
            "old_string": "non_existent_text",
            "new_string": "abc"
        })
        self.assertIn("Error:", res_not_found)
        self.assertIn("not found", res_not_found)

        # Multiple occurrences error
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("dup\ndup\n")
        res_dup = await tool.execute({
            "path": file_path,
            "old_string": "dup",
            "new_string": "unique"
        })
        self.assertIn("matches 2 occurrences", res_dup)

    async def test_shell_tool(self):
        tool = ShellTool()
        # Successful command execution
        res = await tool.execute({"command": "echo 'hello shell'"})
        self.assertIn("hello shell", res)

        # Command with output and exit code
        res_err = await tool.execute({"command": "echo 'error msg' >&2; exit 1"})
        self.assertIn("error msg", res_err)

    async def test_linter_tool(self):
        syntax_path = os.path.join(self.test_dir, "syntax.py")
        with open(syntax_path, "w", encoding="utf-8") as f:
            f.write("def broken(:\n    pass\n")

        syntax_res = await run_linter(syntax_path)
        self.assertIn("[Linter Feedback]", syntax_res)
        self.assertIn("invalid-syntax", syntax_res)

        undefined_path = os.path.join(self.test_dir, "undefined.py")
        with open(undefined_path, "w", encoding="utf-8") as f:
            f.write("print(missing_name)\n")

        undefined_res = await run_linter(undefined_path)
        self.assertIn("[Linter Feedback]", undefined_res)
        self.assertIn("F821", undefined_res)

        long_line_path = os.path.join(self.test_dir, "long_line.py")
        long_value = "a" * 160
        with open(long_line_path, "w", encoding="utf-8") as f:
            f.write(f"value = '{long_value}'\nprint(value)\n")

        long_line_res = await run_linter(long_line_path)
        self.assertEqual("", long_line_res)

        import_order_path = os.path.join(self.test_dir, "import_order.py")
        with open(import_order_path, "w", encoding="utf-8") as f:
            f.write("import sys\nimport os\n\nprint(os.name, sys.version)\n")

        import_order_res = await run_linter(import_order_path)
        self.assertEqual("", import_order_res)

    async def test_tool_aliases_and_case(self):
        from tools.registry import execute_tool
        file_path = os.path.join(self.test_dir, "alias_test.txt")

        # Test capitalized tool name "Create"
        res_create = await execute_tool("Create", {"path": file_path, "content": "Alias Content"})
        self.assertIn("Success: file", res_create)
        self.assertTrue(os.path.exists(file_path))

        # Test alias "write" -> "create"
        file_path2 = os.path.join(self.test_dir, "write_test.txt")
        res_write = await execute_tool("write", {"path": file_path2, "content": "Write Content"})
        self.assertIn("Success: file", res_write)

        # Test alias "cat" -> "read"
        res_cat = await execute_tool("cat", {"path": file_path2})
        self.assertIn("Write Content", res_cat)

        # Test canonical shell tool
        res_shell = await execute_tool("shell", {"command": "echo 'shell command'"})
        self.assertIn("shell command", res_shell)

    async def test_read_tool_max_size_limit(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "large_file.txt")
        with open(file_path, "w") as f:
            f.write("dummy")
        from unittest.mock import patch
        with patch("os.path.getsize", return_value=20 * 1024 * 1024):
            res = await tool.execute({"path": file_path})
            self.assertIn("exceeds maximum readable size", res)

    async def test_format_line_pagination_string_args(self):
        from tools.utils import format_line_pagination
        lines = ["line 1", "line 2", "line 3", "line 4"]
        res = format_line_pagination(lines, start_line="2", end_line="3")
        self.assertIn("line 2", res)
        self.assertIn("line 3", res)
        self.assertNotIn("line 1", res)

    async def test_ask_user_validation(self):
        from tools.ask_user import AskUserTool
        tool = AskUserTool()
        # Invalid questions structure
        res = await tool.execute({"questions": [{"invalid_key": "foo"}]})
        self.assertIn("Error: Invalid or missing 'questions' list.", res)

    async def test_replace_file_content_line_range(self):
        from tools.edit import ReplaceFileContentTool
        file_path = os.path.join(self.test_dir, "range_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("val = 1\nval = 1\nval = 1\n")

        tool = ReplaceFileContentTool()
        # Replace val = 1 only on line 2 (start_line=2, end_line=2)
        res = await tool.execute({
            "target_file": file_path,
            "target_content": "val = 1",
            "replacement_content": "val = 42",
            "start_line": 2,
            "end_line": 2
        })
        self.assertIn("-val = 1", res)
        self.assertIn("+val = 42", res)

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(lines, ["val = 1\n", "val = 42\n", "val = 1\n"])

    async def test_replace_file_content_out_of_range_error(self):
        from tools.edit import ReplaceFileContentTool
        file_path = os.path.join(self.test_dir, "range_err.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("first_line = 1\nsecond_line = 2\ntarget_line = 3\n")

        tool = ReplaceFileContentTool()
        # Search for target_line = 3 in lines 1-2 (must fail with line hint error)
        res = await tool.execute({
            "target_file": file_path,
            "target_content": "target_line = 3",
            "replacement_content": "target_line = 99",
            "start_line": 1,
            "end_line": 2
        })
        self.assertIn("Error: target_content not found between lines 1 and 2", res)
        self.assertIn("Target content was found elsewhere around line 3", res)

    async def test_multi_replace_file_content(self):
        from tools.edit import MultiReplaceFileContentTool
        file_path = os.path.join(self.test_dir, "multi_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def fn_one():\n    return 1\n\ndef fn_two():\n    return 2\n")

        tool = MultiReplaceFileContentTool()
        res = await tool.execute({
            "target_file": file_path,
            "replacement_chunks": [
                {
                    "start_line": 1,
                    "end_line": 2,
                    "target_content": "return 1",
                    "replacement_content": "return 100"
                },
                {
                    "start_line": 4,
                    "end_line": 5,
                    "target_content": "return 2",
                    "replacement_content": "return 200"
                }
            ]
        })
        self.assertIn("return 100", res)
        self.assertIn("return 200", res)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("return 100", content)
        self.assertIn("return 200", content)

    async def test_read_tool_800_line_window_and_hint(self):
        file_path = os.path.join(self.test_dir, "long_file.txt")
        # Create a file with 1000 lines
        lines = [f"Line {i}\n" for i in range(1, 1001)]
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        tool = ReadTool()
        res = await tool.execute({"path": file_path})
        self.assertIn("=== Lines 1-800 of 1000", res)
        self.assertIn("[Hint: File has 1000 lines. Use start_line=801 end_line=1000 to read next chunk.]", res)
        self.assertIn("Line 800", res)
        self.assertNotIn("Line 801", res)

    async def test_read_tool_doc_caching(self):
        from tools.read import clear_doc_cache, convert_doc_to_markdown_sync
        clear_doc_cache()
        pdf_path = os.path.join(self.test_dir, "cached_doc.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.7 mock content")

        from unittest.mock import patch
        with patch("tools.read.set_cached_doc_markdown") as mock_set:
            with patch("markitdown.MarkItDown") as mock_md_cls:
                mock_md = mock_md_cls.return_value
                mock_res = type("Result", (), {"text_content": "# Cached Doc Header\nDoc text"})()
                mock_md.convert.return_value = mock_res

                res1 = convert_doc_to_markdown_sync(pdf_path)
                self.assertIn("Cached Doc Header", res1)
                self.assertTrue(mock_set.called)

        clear_doc_cache()


if __name__ == "__main__":
    unittest.main()
