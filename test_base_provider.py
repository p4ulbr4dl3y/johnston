import os
import tempfile
import shutil
import unittest
import asyncio
from tools.registry import execute_tool
from base_provider import BaseAgent

class TestBaseProviderTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    async def test_create_and_read_tool(self):
        file_path = os.path.join(self.test_dir, "test.txt")
        
        # Test Create
        res_create = await execute_tool("Create", {"path": file_path, "content": "hello world"})
        self.assertIn("Success", res_create)
        self.assertTrue(os.path.exists(file_path))
        
        # Test Read
        res_read = await execute_tool("Read", {"path": file_path})
        self.assertEqual(res_read, "hello world")

    async def test_read_missing_file(self):
        file_path = os.path.join(self.test_dir, "missing.txt")
        res_read = await execute_tool("Read", {"path": file_path})
        self.assertIn("Error", res_read)

    async def test_edit_tool(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("Create", {"path": file_path, "content": "line1\nline2\nline3"})
        
        # Test valid Edit
        res_edit = await execute_tool("Edit", {
            "path": file_path,
            "old_string": "line2",
            "new_string": "line_two"
        })
        self.assertIn("line2", res_edit)  # check diff contains old text
        self.assertIn("line_two", res_edit)  # check diff contains new text
        
        # Verify content
        with open(file_path, "r") as f:
            content = f.read()
        self.assertEqual(content, "line1\nline_two\nline3")

    async def test_edit_missing_text(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("Create", {"path": file_path, "content": "line1\nline2\nline3"})
        
        res_edit = await execute_tool("Edit", {
            "path": file_path,
            "old_string": "missing_line",
            "new_string": "replacement"
        })
        self.assertIn("Error", res_edit)

    async def test_glob_tool(self):
        os.makedirs(os.path.join(self.test_dir, "subdir"))
        await execute_tool("Create", {"path": os.path.join(self.test_dir, "file1.txt"), "content": "a"})
        await execute_tool("Create", {"path": os.path.join(self.test_dir, "subdir", "file2.log"), "content": "b"})
        
        # Glob txt
        res_glob = await execute_tool("Glob", {"pattern": "*.txt"})
        self.assertIn("file1.txt", res_glob)
        self.assertNotIn("file2.log", res_glob)

    async def test_grep_tool(self):
        file1 = os.path.join(self.test_dir, "file1.txt")
        file2 = os.path.join(self.test_dir, "file2.txt")
        await execute_tool("Create", {"path": file1, "content": "banana apple pear"})
        await execute_tool("Create", {"path": file2, "content": "grape orange cherry"})
        
        # Grep apple
        res_grep = await execute_tool("Grep", {"pattern": "apple"})
        self.assertIn("file1.txt", res_grep)
        self.assertIn("banana apple pear", res_grep)
        self.assertNotIn("file2.txt", res_grep)

    async def test_bash_tool_sync(self):
        # Sync bash execution
        res_bash = await execute_tool("Bash", {"command": "echo 'hello bash'"})
        self.assertEqual(res_bash.strip(), "hello bash")

if __name__ == "__main__":
    unittest.main()
