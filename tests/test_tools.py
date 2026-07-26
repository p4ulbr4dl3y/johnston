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
        from tools.context import ToolContext
        ToolContext._instance = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name

    def tearDown(self):
        from tools.context import ToolContext
        ToolContext._instance = None
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
        # Test run_linter helper function
        file_path = os.path.join(self.test_dir, "syntax.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("import os\nimport sys\n")
        res = await run_linter(file_path)
        self.assertIsInstance(res, str)

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


if __name__ == "__main__":
    unittest.main()
