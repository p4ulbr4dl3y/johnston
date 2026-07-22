import os
import tempfile
import unittest

from tools.bash import BashTool
from tools.create import CreateTool
from tools.edit import EditTool
from tools.glob import GlobTool
from tools.grep import GrepTool
from tools.linter import run_linter
from tools.list_dir import ListDirTool
from tools.read import ReadTool


class MockAgent:
    def __init__(self, mode="plan"):
        self.mode = mode

class MockApp:
    def __init__(self, mode="plan"):
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

    def tearDown(self):
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

    async def test_bash_tool(self):
        tool = BashTool()
        # Successful command execution
        res = await tool.execute({"command": "echo 'hello bash'"})
        self.assertIn("hello bash", res)

        # Command with output and exit code
        res_err = await tool.execute({"command": "echo 'error msg' >&2; exit 1"})
        self.assertIn("error msg", res_err)

    async def test_grep_glob_listdir_tools(self):
        # Create test files
        file1 = os.path.join(self.test_dir, "test1.py")
        file2 = os.path.join(self.test_dir, "test2.txt")
        with open(file1, "w", encoding="utf-8") as f:
            f.write("def search_target(): pass\n")
        with open(file2, "w", encoding="utf-8") as f:
            f.write("no match here\n")

        # GrepTool
        grep_tool = GrepTool()
        res_grep = await grep_tool.execute({"path": self.test_dir, "pattern": "search_target"})
        self.assertIn("test1.py", res_grep)
        self.assertIn("search_target", res_grep)

        # GlobTool
        glob_tool = GlobTool()
        res_glob = await glob_tool.execute({"path": self.test_dir, "pattern": "*.py"})
        self.assertIn("test1.py", res_glob)
        self.assertNotIn("test2.txt", res_glob)

        # ListDirTool
        list_tool = ListDirTool()
        res_list = await list_tool.execute({"path": self.test_dir})
        self.assertIn("test1.py", res_list)
        self.assertIn("test2.txt", res_list)

    async def test_switch_to_action_tool(self):
        from tools.switch_to_action import SwitchToActionTool
        tool = SwitchToActionTool()
        app = MockApp(mode="explore")

        # Execute switch_to_action in explore mode
        res = await tool.execute({"explanation": "User approved"}, app=app)
        self.assertIn("Switched to Action mode", res)
        self.assertEqual(app.agent.mode, "action")

    async def test_linter_tool(self):
        # Test run_linter helper function
        file_path = os.path.join(self.test_dir, "syntax.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("import os\nimport sys\n")
        res = await run_linter(file_path)
        self.assertIsInstance(res, str)


if __name__ == "__main__":
    unittest.main()
