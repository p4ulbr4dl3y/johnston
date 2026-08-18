import os
import tempfile
import unittest

from tests.conftest import WindowsSafeTemporaryDirectory
from tools.create import CreateTool
from tools.edit import EditTool, MultiEditTool
from tools.read import ReadTool
from tools.shell import ShellTool


class MockAgent:
    def __init__(self, role="explorer"):
        self.role = role


class MockApp:
    def __init__(self, role="explorer"):
        self.agent = MockAgent(role=role)
        self.notified = []

    def notify(self, msg: str):
        self.notified.append(msg)

    def refresh_status_footer(self):
        pass


class TestTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = WindowsSafeTemporaryDirectory()
        self.test_dir = self.temp_dir.name
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        # Grant the tools that used to be 'allow' via the removed read/write groups.
        pm.set_session_override("shell", "allow")
        pm.set_session_override("read", "allow")
        pm.set_session_override("create", "allow")
        pm.set_session_override("edit", "allow")
        pm.set_session_override("multi_edit", "allow")

    async def test_create_allows_johnston_config(self):
        tool = CreateTool()
        target = os.path.join(self.test_dir, ".johnston", "config.json")
        res = str(await tool.execute({"path": target, "content": '{"permissions": {}}'}))
        self.assertIn("file", res)
        self.assertTrue(os.path.exists(target))

    async def test_edit_allows_johnston_config(self):
        tool = EditTool()
        target = os.path.join(self.test_dir, ".johnston", "roles", "custom.md")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("old")
        res = str(await tool.execute({"path": target, "old_str": "old", "new_str": "new"}))
        self.assertNotIn("ERR:", res)
        self.assertIn("-old", res)
        self.assertIn("+new", res)
        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp_dir.cleanup()

    async def test_read_tool(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "sample.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n")

        # Full read
        res = str(await tool.execute({"path": file_path}))
        self.assertIn("Line 1", res)
        self.assertIn("Line 5", res)

        # Range read
        res_range = str(await tool.execute({"path": file_path, "start_line": 2, "end_line": 4}))
        self.assertIn("Lines 2-4", res_range)
        self.assertIn("Line 2", res_range)
        self.assertNotIn("Line 5", res_range)

        # Start line out of bounds
        res_oob = str(await tool.execute({"path": file_path, "start_line": 50}))
        self.assertIn("exceeds total file line count", res_oob)
        self.assertIn("[Hint:", res_oob)

        # Non-existent file
        res_err = str(await tool.execute({"path": os.path.join(self.test_dir, "missing.txt")}))
        self.assertIn("ERR:", res_err)

        # Directory read (should auto-list directory contents with hint)
        dir_res = str(await tool.execute({"path": self.test_dir}))
        self.assertIn("is a directory", dir_res)
        self.assertIn("sample.txt", dir_res)
        self.assertIn("Hint:", dir_res)

        # Directory truncation test (>60 items)
        large_dir = os.path.join(self.test_dir, "large_folder")
        os.makedirs(large_dir, exist_ok=True)
        for i in range(70):
            with open(os.path.join(large_dir, f"file_{i:02d}.txt"), "w") as f:
                f.write("test")
        large_dir_res = str(await tool.execute({"path": large_dir}))
        self.assertIn("items truncated", large_dir_res)
        self.assertIn("Total: 70 items", large_dir_res)

        # External file outside workspace allowed
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as ext_f:
            ext_f.write("External content")
            ext_path = ext_f.name
        try:
            ext_res = str(await tool.execute({"path": ext_path}))
            self.assertIn("External content", ext_res)
        finally:
            if os.path.exists(ext_path):
                os.remove(ext_path)

        # Plain text HTML file (read as raw text without markitdown)
        html_path = os.path.join(self.test_dir, "doc.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<h1>Test HTML</h1>")
        res_html = str(await tool.execute({"path": html_path}))
        self.assertIn("<h1>Test HTML</h1>", res_html)

        # PDF document format via markitdown conversion
        pdf_path = os.path.join(self.test_dir, "doc.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.7 mock content")

        from unittest.mock import patch

        with patch("tools.read.convert_doc_to_markdown_sync", return_value="# Converted PDF Header\nPDF body text"):
            res_pdf = str(await tool.execute({"path": pdf_path}))
            self.assertIn("Converted PDF Header", res_pdf)

    async def test_create_tool(self):
        tool = CreateTool()
        file_path = os.path.join(self.test_dir, "nested", "new_file.txt")

        # Create file in non-existent directory
        res = str(await tool.execute({"path": file_path, "content": "Hello World"}))
        self.assertIn("file", res)
        self.assertTrue(os.path.exists(file_path))

        # Update existing file (should return diff and updated status)
        res_update = str(await tool.execute({"path": file_path, "content": "Hello Universe"}))
        self.assertIn("file", res_update)
        self.assertIn("-Hello World", res_update)
        self.assertIn("+Hello Universe", res_update)

        # Create file over existing directory error
        res_dir_err = str(await tool.execute({"path": self.test_dir, "content": "Hello World"}))
        self.assertIn("is a directory", res_dir_err)

    async def test_edit_tool(self):
        tool = EditTool()
        read_tool = ReadTool()
        file_path = os.path.join(self.test_dir, "code.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def foo():\n    return 42\n")
        await read_tool.execute({"path": file_path})

        # Edit on directory error
        res_edit_dir = str(await tool.execute(
            {"path": self.test_dir, "old_str": "a", "new_str": "b"}
        ))
        self.assertIn("is a directory", res_edit_dir)

        # Successful edit
        res = str(await tool.execute(
            {"path": file_path, "old_str": "return 42", "new_str": "return 100"}
        ))
        self.assertIn("-    return 42", res)
        self.assertIn("+    return 100", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "def foo():\n    return 100\n")

        # Edit with curly quote normalization
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("msg = “hello”\n")
        await read_tool.execute({"path": file_path})
        await tool.execute(
            {"path": file_path, "old_str": 'msg = "hello"', "new_str": 'msg = "world"'}
        )
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "msg = ”world”\n")

        # Edit with deletion stripping trailing newline
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\n")
        await read_tool.execute({"path": file_path})
        await tool.execute({"path": file_path, "old_str": "line2", "new_str": ""})
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "line1\nline3\n")

        # Old string not found error
        res_not_found = str(await tool.execute({"path": file_path, "old_str": "non_existent_text", "new_str": "abc"}))
        self.assertIn("ERR:", res_not_found)
        self.assertIn("not found", res_not_found)

        # Multiple occurrences error
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("dup\ndup\n")
        await read_tool.execute({"path": file_path})
        res_dup = str(await tool.execute({"path": file_path, "old_str": "dup", "new_str": "unique"}))
        self.assertIn("matches 2 occurrences", res_dup)

    async def test_shell_tool(self):
        tool = ShellTool()
        # Successful command execution
        res = str(await tool.execute({"command": "echo 'hello shell'"}))
        self.assertIn("hello shell", res)

        # Command with output and exit code
        res_err = str(await tool.execute({"command": "echo 'error msg' >&2; exit 1"}))
        self.assertIn("error msg", res_err)

    async def test_tool_case_and_canonical(self):
        from tools.registry import execute_tool

        file_path = os.path.join(self.test_dir, "case_test.txt")

        # Test capitalized tool name "Create"
        res_create = await execute_tool("Create", {"path": file_path, "content": "Case Content"})
        self.assertIn("file", res_create.content)
        self.assertTrue(os.path.exists(file_path))

        # Aliases are no longer resolved: 'write' is unknown, only 'create' works.
        file_path2 = os.path.join(self.test_dir, "case_test2.txt")
        res_write = await execute_tool("write", {"path": file_path2, "content": "Write Content"})
        self.assertIn("ERR: unknown 'write'", res_write.content)
        self.assertFalse(os.path.exists(file_path2))

        # Similar alias 'cat' is also unknown; canonical 'read' returns content.
        res_cat = await execute_tool("cat", {"path": file_path})
        self.assertIn("ERR: unknown 'cat'", res_cat.content)
        res_read = await execute_tool("Read", {"path": file_path})
        self.assertIn("Case Content", res_read.content)

        # Test canonical shell tool
        res_shell = await execute_tool("shell", {"command": "echo 'shell command'"})
        self.assertIn("shell command", res_shell.content)

    async def test_read_tool_max_size_limit(self):
        tool = ReadTool()
        file_path = os.path.join(self.test_dir, "large_file.txt")
        with open(file_path, "w") as f:
            f.write("dummy")
        from unittest.mock import patch

        with patch("os.path.getsize", return_value=20 * 1024 * 1024):
            res = str(await tool.execute({"path": file_path}))
            self.assertIn("exceeds 10MB", res)

    async def test_format_line_pagination_string_args(self):
        from tools.utils import format_line_pagination

        lines = ["line 1", "line 2", "line 3", "line 4"]
        res = format_line_pagination(lines, start_line="2", end_line="3")
        self.assertIn("line 2", res)
        self.assertIn("line 3", res)
        self.assertNotIn("line 1", res)

    async def test_format_line_pagination_max_800_cap(self):
        from tools.utils import format_line_pagination

        lines = [f"line {i}" for i in range(1, 1500)]
        res = format_line_pagination(lines, start_line=1, end_line=1200)
        self.assertIn("Lines 1-800 of 1499", res)

    async def test_format_line_pagination_char_limit_line_boundary(self):
        from tools.utils import format_line_pagination

        long_line = "x" * 100
        lines = [long_line for _ in range(500)]
        # max_chars=300 -> each line formatted is ~109 chars ("    1 | x...x")
        # 2 complete lines ~219 chars fit, 3 lines exceed 300
        res = format_line_pagination(lines, start_line=1, end_line=500, max_chars=300)
        self.assertIn("Lines 1-2 of 500", res)
        self.assertIn("Use start_line=3", res)
        self.assertIn(
            "Warning: Output truncated at line 2 before target line 500 due to character limit (300 chars)", res
        )

    async def test_ask_user_validation(self):
        from tools.ask_user import AskUserTool

        tool = AskUserTool()
        # Invalid questions structure
        res = str(await tool.execute({"questions": [{"invalid_key": "foo"}]}))
        self.assertIn("ERR: params 'questions': missing or invalid", res)

    async def test_edit_line_range(self):
        from tools.edit import EditTool

        file_path = os.path.join(self.test_dir, "range_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("val = 1\nval = 1\nval = 1\n")
        await ReadTool().execute({"path": file_path})

        tool = EditTool()
        # Replace val = 1 only on line 2 (start_line=2, end_line=2)
        res = str(await tool.execute(
            {
                "path": file_path,
                "old_str": "val = 1",
                "new_str": "val = 42",
                "start_line": 2,
                "end_line": 2,
            }
        ))
        self.assertIn("-val = 1", res)
        self.assertIn("+val = 42", res)

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertEqual(lines, ["val = 1\n", "val = 42\n", "val = 1\n"])

    async def test_edit_out_of_range_error(self):
        from tools.edit import EditTool

        file_path = os.path.join(self.test_dir, "range_err.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("first_line = 1\nsecond_line = 2\ntarget_line = 3\ntarget_line = 3\n")
        await ReadTool().execute({"path": file_path})

        tool = EditTool()
        # Search for target_line = 3 in lines 1-2 when multiple exist in file
        res = str(await tool.execute(
            {
                "path": file_path,
                "old_str": "target_line = 3",
                "new_str": "target_line = 99",
                "start_line": 1,
                "end_line": 2,
            }
        ))
        self.assertIn("ERR: match: target not found in specified range", res)
        self.assertIn("matches multiple occurrences (2)", res)

    async def test_edit_tool_line_range_miss_fallback(self):
        from tools.edit import EditTool

        file_path = os.path.join(self.test_dir, "fallback_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("val_a = 1\nval_b = 2\nunique_target = 42\nval_c = 4\n")
        await ReadTool().execute({"path": file_path})

        tool = EditTool()
        # Range 1-2 does not include unique_target = 42 (line 3), but fallback succeeds because it is unique!
        res = str(await tool.execute(
            {
                "path": file_path,
                "old_str": "unique_target = 42",
                "new_str": "unique_target = 100",
                "start_line": 1,
                "end_line": 2,
            }
        ))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertIn("unique_target = 100", f.read())

        # Start line out of bounds, but target unique in file -> fallback succeeds!
        res_oob = str(await tool.execute(
            {
                "path": file_path,
                "old_str": "unique_target = 100",
                "new_str": "unique_target = 200",
                "start_line": 50,
                "end_line": 60,
            }
        ))
        self.assertNotIn("ERR:", res_oob)
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertIn("unique_target = 200", f.read())

    async def test_edit_tool_end_line_auto_expansion(self):
        from tools.edit import EditTool

        file_path = os.path.join(self.test_dir, "auto_expand.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def sample():\n    a = 1\n    b = 2\n    c = 3\n    return a + b + c\n")
        await ReadTool().execute({"path": file_path})

        tool = EditTool()
        # old_str is 3 lines starting at start_line=2, but end_line=3 (too short for 3 lines)
        res = str(await tool.execute(
            {
                "path": file_path,
                "old_str": "    a = 1\n    b = 2\n    c = 3",
                "new_str": "    a = 10\n    b = 20\n    c = 30",
                "start_line": 2,
                "end_line": 3,
            }
        ))
        self.assertNotIn("ERR:", res)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("a = 10", content)
        self.assertIn("b = 20", content)

    async def test_multi_edit(self):
        file_path = os.path.join(self.test_dir, "multi_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def fn_one():\n    return 1\n\ndef fn_two():\n    return 2\n")
        await ReadTool().execute({"path": file_path})

        tool = MultiEditTool()
        res = str(await tool.execute(
            {
                "path": file_path,
                "edits": [
                    {"start_line": 1, "end_line": 2, "old_str": "return 1", "new_str": "return 100"},
                    {"start_line": 4, "end_line": 5, "old_str": "return 2", "new_str": "return 200"},
                ],
            }
        ))
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
        res = str(await tool.execute({"path": file_path}))
        self.assertIn("=== Lines 1-800 of 1000", res)
        self.assertIn("[Hint: File has 1000 lines. Use start_line=801 end_line=1000 to read next chunk.]", res)
        self.assertIn("Line 800", res)
        self.assertNotIn("Line 801", res)

    async def test_read_tool_doc_caching(self):
        from tools.read import convert_doc_to_markdown_sync

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

    async def test_read_tool_image_support(self):
        import json

        from PIL import Image

        img_path = os.path.join(self.test_dir, "sample.png")
        img = Image.new("RGB", (2000, 1000), color=(255, 0, 0))
        img.save(img_path, format="PNG")

        tool = ReadTool()
        res = str(await tool.execute({"path": img_path}))
        data = json.loads(res)
        self.assertEqual(data["type"], "image")
        self.assertEqual(data["path"], img_path)
        self.assertIn("base64", data)
        self.assertIn("sample.png", data["summary"])
        # Check resizing to max_dim 1568 (2000x1000 -> 1568x784)
        self.assertEqual(data["dimensions"], [1568, 784])

    async def test_read_tool_image_detail_modes(self):
        import json

        from PIL import Image

        img_path = os.path.join(self.test_dir, "sample_detail.jpg")
        img = Image.new("RGB", (3000, 3000), color=(0, 255, 0))
        img.save(img_path, format="JPEG")

        tool = ReadTool()
        # low detail -> max 512px
        res_low = str(await tool.execute({"path": img_path, "detail": "low"}))
        data_low = json.loads(res_low)
        self.assertEqual(data_low["dimensions"], [512, 512])

        # high detail -> max 2048px
        res_high = str(await tool.execute({"path": img_path, "detail": "high"}))
        data_high = json.loads(res_high)
        self.assertEqual(data_high["dimensions"], [2048, 2048])

    async def test_read_tool_corrupt_image_error(self):
        corrupt_path = os.path.join(self.test_dir, "corrupt.png")
        with open(corrupt_path, "wb") as f:
            f.write(b"not an image file binary junk")

        tool = ReadTool()
        res = str(await tool.execute({"path": corrupt_path}))
        self.assertIn("ERR: image", res)


if __name__ == "__main__":
    unittest.main()
