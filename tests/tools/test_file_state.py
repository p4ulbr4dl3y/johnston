import os
import tempfile
import time
import unittest

from tools.create import CreateTool
from tools.edit import EditTool
from tools.file_state import _FILE_READ_STATE
from tools.read import ReadTool


class TestFileState(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _FILE_READ_STATE.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = self.temp_dir.name

    def tearDown(self):
        _FILE_READ_STATE.clear()
        self.temp_dir.cleanup()

    async def test_file_state_flow(self):
        read_tool = ReadTool()
        create_tool = CreateTool()
        edit_tool = EditTool()

        file_path = os.path.join(self.test_dir, "test.txt")

        # 1. New file creation: allowed without prior read
        res_create = await create_tool.execute({"path": file_path, "content": "initial content"})
        self.assertIn("OK: file", res_create)

        # 2. Edit without read: allowed because create_tool recorded file write
        res_edit = await edit_tool.execute({
            "target_file": file_path,
            "target_content": "initial content",
            "replacement_content": "edited content"
        })
        self.assertIn("-initial content", res_edit)

        # 3. Simulate external modification without read
        time.sleep(0.02)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("externally modified content")

        # 4. Attempt edit after external modification -> Should fail with modification error
        res_stale = await edit_tool.execute({
            "target_file": file_path,
            "target_content": "externally modified content",
            "replacement_content": "new"
        })
        self.assertIn("modified since it was last read", res_stale)

        # 5. Read tool resolves the stale state
        res_read = await read_tool.execute({"path": file_path})
        self.assertIn("externally modified content", res_read)

        # 6. Now edit succeeds
        res_edit2 = await edit_tool.execute({
            "target_file": file_path,
            "target_content": "externally modified content",
            "replacement_content": "fresh content"
        })
        self.assertIn("fresh content", res_edit2)

    async def test_existing_file_requires_read(self):
        create_tool = CreateTool()
        edit_tool = EditTool()

        existing_path = os.path.join(self.test_dir, "existing.txt")
        with open(existing_path, "w", encoding="utf-8") as f:
            f.write("old data")

        # Edit on existing file without reading -> ERR
        res_edit = await edit_tool.execute({
            "target_file": existing_path,
            "target_content": "old data",
            "replacement_content": "new data"
        })
        self.assertIn("has not been read yet", res_edit)

        # Create/Update on existing file without reading -> ERR
        res_update = await create_tool.execute({"path": existing_path, "content": "overwrite"})
        self.assertIn("has not been read yet", res_update)
