import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from core.domain.defaults.errors import ToolResultStatus
from tools.context import ToolContext
from tools.registry import REGISTRY, execute_tool
from tools.search import (
    SearchTool,
    _match_glob,
    is_binary_file,
    search_sync,
)
from widgets.presentation.tool_display import extract_tool_display


class TestSearchTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = SearchTool()

        # Create sample files structure
        # tmpdir/
        #   main.py
        #   utils.py
        #   service.ts
        #   binary.bin
        #   image.png
        #   notes.txt
        #   sub/
        #     helper.py
        #     deep.txt
        #   .git/
        #     hidden.py
        #   node_modules/
        #     vendor.js
        #   .venv/
        #     lib.py

        self.main_py = os.path.join(self.tmpdir, "main.py")
        with open(self.main_py, "w", encoding="utf-8") as f:
            f.write(
                "import os\n\n"
                "class AppRunner:\n"
                "    def __init__(self, name: str):\n"
                "        self.name = name\n\n"
                "    def run(self):\n"
                "        print(f'Running {self.name}')\n\n"
                "async def start_server(host, port=8080):\n"
                "    print('Server listening')\n"
            )

        self.utils_py = os.path.join(self.tmpdir, "utils.py")
        with open(self.utils_py, "w", encoding="utf-8") as f:
            f.write(
                "def calculate_total(items, *args, **kwargs):\n"
                "    return sum(items)\n\n"
                "def helper_func():\n"
                "    pass\n"
            )

        self.service_ts = os.path.join(self.tmpdir, "service.ts")
        with open(self.service_ts, "w", encoding="utf-8") as f:
            f.write(
                "export class UserService {\n"
                "    getUser(id: string) {}\n"
                "}\n\n"
                "export function fetchAuthToken(user: string): string {\n"
                "    return 'token';\n"
                "}\n\n"
                "interface UserConfig {\n"
                "    role: string;\n"
                "}\n"
            )

        self.notes_txt = os.path.join(self.tmpdir, "notes.txt")
        with open(self.notes_txt, "w", encoding="utf-8") as f:
            f.write("Important note: AppRunner is the main entry point.\n")

        self.binary_bin = os.path.join(self.tmpdir, "binary.bin")
        with open(self.binary_bin, "wb") as f:
            f.write(b"header\x00data\x00content")

        self.image_png = os.path.join(self.tmpdir, "image.png")
        with open(self.image_png, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        sub_dir = os.path.join(self.tmpdir, "sub")
        os.makedirs(sub_dir, exist_ok=True)
        self.sub_helper = os.path.join(sub_dir, "helper.py")
        with open(self.sub_helper, "w", encoding="utf-8") as f:
            f.write("def sub_helper():\n    return 42\n")

        git_dir = os.path.join(self.tmpdir, ".git")
        os.makedirs(git_dir, exist_ok=True)
        with open(os.path.join(git_dir, "hidden.py"), "w", encoding="utf-8") as f:
            f.write("def git_hidden():\n    return 'secret'\n")

        node_dir = os.path.join(self.tmpdir, "node_modules")
        os.makedirs(node_dir, exist_ok=True)
        with open(os.path.join(node_dir, "vendor.js"), "w", encoding="utf-8") as f:
            f.write("function vendorLib() {}\n")

        venv_dir = os.path.join(self.tmpdir, ".venv")
        os.makedirs(venv_dir, exist_ok=True)
        with open(os.path.join(venv_dir, "lib.py"), "w", encoding="utf-8") as f:
            f.write("def venv_func(): pass\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_schema_and_properties(self):
        self.assertEqual(self.tool.name, "search")
        self.assertTrue(self.tool.is_concurrency_safe())
        schema = self.tool.get_schema()
        self.assertIn("function", schema)
        params = schema["function"]["parameters"]
        self.assertIn("query", params["properties"])
        self.assertIn("path", params["properties"])
        self.assertIn("mode", params["properties"])
        self.assertIn("glob", params["properties"])
        self.assertIn("case_sensitive", params["properties"])
        self.assertIn("max_results", params["properties"])
        self.assertIn("context_lines", params["properties"])
        self.assertEqual(params["required"], ["query"])

    def test_binary_file_detection(self):
        self.assertTrue(is_binary_file(self.binary_bin))
        self.assertTrue(is_binary_file(self.image_png))
        self.assertFalse(is_binary_file(self.main_py))
        self.assertFalse(is_binary_file(self.notes_txt))

    def test_match_glob(self):
        self.assertTrue(_match_glob("main.py", "main.py", "*.py"))
        self.assertFalse(_match_glob("notes.txt", "notes.txt", "*.py"))
        self.assertTrue(_match_glob("main.py", "main.py", "*.py,*.txt"))
        self.assertTrue(_match_glob("notes.txt", "notes.txt", "*.py,*.txt"))
        self.assertFalse(_match_glob("sub/test.py", "test.py", "*.py,!*test*"))
        self.assertTrue(_match_glob("sub/helper.py", "helper.py", "*.py,!*test*"))

    async def test_content_search_python_fallback(self):
        # Force pure Python fallback by patching shutil.which
        with patch("shutil.which", return_value=None):
            ctx = ToolContext(cwd=self.tmpdir)
            res = await self.tool.execute({"query": "AppRunner", "path": "."}, ctx=ctx)
            self.assertEqual(res.status, ToolResultStatus.DONE)
            self.assertIn("[search=content", res.content)
            self.assertIn("main.py", res.content)
            self.assertIn("AppRunner", res.content)
            self.assertIn("notes.txt", res.content)
            # Must exclude .git, .venv, node_modules
            self.assertNotIn(".git", res.content)
            self.assertNotIn(".venv", res.content)
            self.assertNotIn("node_modules", res.content)

    async def test_content_search_with_ripgrep(self):
        if not shutil.which("rg"):
            self.skipTest("rg binary not installed")
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "AppRunner", "path": "."}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("[search=content", res.content)
        self.assertIn("AppRunner", res.content)
        self.assertNotIn(".git", res.content)
        self.assertNotIn("node_modules", res.content)

    async def test_content_search_case_sensitivity(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Case-insensitive match
        res1 = await self.tool.execute({"query": "apprunner", "case_sensitive": False}, ctx=ctx)
        self.assertIn("AppRunner", res1.content)

        # Case-sensitive match
        res2 = await self.tool.execute({"query": "apprunner", "case_sensitive": True}, ctx=ctx)
        self.assertIn("0 matches found", res2.content)

    async def test_content_search_glob_filter(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Filter to only .py files
        res = await self.tool.execute({"query": "AppRunner", "glob": "*.py"}, ctx=ctx)
        self.assertIn("main.py", res.content)
        self.assertNotIn("notes.txt", res.content)

    async def test_content_search_context_lines(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute(
            {"query": "def run", "path": "main.py", "context_lines": 1},
            ctx=ctx,
        )
        self.assertIn("main.py:7:", res.content)
        self.assertIn("def run(self)", res.content)
        self.assertIn("main.py-6-", res.content)
        self.assertIn("main.py-8-", res.content)

    async def test_content_search_regex_and_invalid_regex_fallback(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Valid regex
        res = await self.tool.execute({"query": r"def\s+\w+\("}, ctx=ctx)
        self.assertIn("def calculate_total", res.content)

        # Invalid regex syntax falls back to literal search gracefully
        with patch("shutil.which", return_value=None):
            res_bad = await self.tool.execute({"query": "[unclosed"}, ctx=ctx)
            self.assertIn("0 matches found", res_bad.content)

    async def test_content_search_single_file(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "calculate_total", "path": "utils.py"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("calculate_total", res.content)

    async def test_filename_mode(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "helper", "mode": "filename"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("helper.py", res.content)
        self.assertNotIn("hidden.py", res.content)

    async def test_filename_mode_wildcard(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "*", "mode": "filename", "glob": "*.py"}, ctx=ctx)
        self.assertIn("main.py", res.content)
        self.assertIn("utils.py", res.content)
        self.assertNotIn("notes.txt", res.content)

    async def test_outline_mode_python(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "*", "path": "main.py", "mode": "outline"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("class AppRunner:", res.content)
        self.assertIn("def run(self)", res.content)
        self.assertIn("async def start_server(host, port)", res.content)

    async def test_outline_mode_with_symbol_query(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Search for specific function symbol
        res = await self.tool.execute({"query": "calculate_total", "mode": "outline"}, ctx=ctx)
        self.assertIn("def calculate_total", res.content)
        self.assertNotIn("helper_func", res.content)

    async def test_outline_mode_generic_ts(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "*", "path": "service.ts", "mode": "outline"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("class UserService", res.content)
        self.assertIn("function fetchAuthToken", res.content)
        self.assertIn("interface UserConfig", res.content)

    async def test_outline_mode_directory(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "*", "mode": "outline", "glob": "*.py"}, ctx=ctx)
        self.assertIn("main.py:", res.content)
        self.assertIn("utils.py:", res.content)
        self.assertNotIn("service.ts:", res.content)

    async def test_error_handling_not_found(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "foo", "path": "nonexistent_dir_123"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.ERROR)
        self.assertIn("ERR: not_found", res.content)

    async def test_error_handling_invalid_mode(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "foo", "mode": "invalid_mode"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.ERROR)
        self.assertIn("ERR: params", res.content)
        self.assertIn("invalid mode", res.content)

    async def test_error_handling_missing_query_content_mode(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "", "mode": "content"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.ERROR)
        self.assertIn("ERR: params", res.content)
        self.assertIn("query parameter is required", res.content)

    async def test_sandbox_permission_block(self):
        ctx = MagicMock()
        ctx.cwd = self.tmpdir
        ctx.sandbox_enabled = True
        with patch("core.infrastructure.platform.sandbox.is_path_readable_in_sandbox", return_value=False):
            res = await self.tool.execute({"query": "foo", "path": "/etc/passwd"}, ctx=ctx)
            self.assertEqual(res.status, ToolResultStatus.ERROR)
            self.assertIn("ERR: permission", res.content)
            self.assertIn("sandbox restriction", res.content)

    async def test_cancellation(self):
        cancel_event = threading.Event()
        cancel_event.set()
        res = search_sync(
            query="AppRunner",
            path=self.tmpdir,
            cwd=self.tmpdir,
            cancel_event=cancel_event,
        )
        # Should exit early with 0 matches or minimal work
        self.assertIn("0 matches found", res.content)

    def test_extract_tool_display_chip(self):
        d1 = extract_tool_display("search", {"query": "AppRunner", "path": "src"})
        self.assertEqual(d1, '"AppRunner" in src')

        d2 = extract_tool_display("search", {"query": "run", "mode": "outline"})
        self.assertEqual(d2, 'outline "run"')

        d3 = extract_tool_display("search", {})
        self.assertEqual(d3, "codebase")

    async def test_max_results_capping_content(self):
        # Generate file with 10 matching lines
        p = os.path.join(self.tmpdir, "many.txt")
        with open(p, "w") as f:
            for i in range(20):
                f.write(f"match_item_{i}\n")

        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "match_item", "path": "many.txt", "max_results": 5}, ctx=ctx)
        self.assertIn("matches=5", res.content)

    async def test_outline_syntax_error_file(self):
        broken = os.path.join(self.tmpdir, "broken.py")
        with open(broken, "w") as f:
            f.write("def invalid_syntax(:\n")

        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "*", "path": "broken.py", "mode": "outline"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("0 matches found", res.content)

    async def test_outline_other_languages(self):
        # Go file
        go_file = os.path.join(self.tmpdir, "server.go")
        with open(go_file, "w") as f:
            f.write(
                "package main\n\n"
                "func HandleRequest(w http.ResponseWriter, r *http.Request) {}\n"
                "type ServerConfig struct {}\n"
            )

        # Rust file
        rs_file = os.path.join(self.tmpdir, "lib.rs")
        with open(rs_file, "w") as f:
            f.write(
                "pub fn process_event() {}\n"
                "struct EventQueue {}\n"
            )

        ctx = ToolContext(cwd=self.tmpdir)
        res_go = await self.tool.execute({"query": "*", "path": "server.go", "mode": "outline"}, ctx=ctx)
        self.assertIn("HandleRequest", res_go.content)

        res_rs = await self.tool.execute({"query": "*", "path": "lib.rs", "mode": "outline"}, ctx=ctx)
        self.assertIn("process_event", res_rs.content)
        self.assertIn("EventQueue", res_rs.content)

    async def test_ripgrep_failure_falls_back_to_python(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Mock ripgrep raising an exception to test graceful python fallback
        with patch("subprocess.Popen", side_effect=OSError("rg failed")):
            res = await self.tool.execute({"query": "AppRunner", "path": "."}, ctx=ctx)
            self.assertEqual(res.status, ToolResultStatus.DONE)
            self.assertIn("AppRunner", res.content)

    def test_ripgrep_line_parsing_windows_and_hyphens(self):
        from tools.search import _search_content_ripgrep

        mock_stdout = (
            "C:\\repo\\main.py:10:def hello():\n"
            "test-runner.py-12-    context_call()\n"
            "test-runner.py:13:    runner_test()\n"
        )
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (mock_stdout, "")

        with patch("subprocess.Popen", return_value=mock_proc):
            lines, count, files_count = _search_content_ripgrep(
                target_path=".", query="test", cwd="C:\\repo"
            )
            self.assertEqual(count, 2)
            self.assertEqual(files_count, 2)
            self.assertTrue(any("main.py:10:def hello():" in ln for ln in lines))
            self.assertTrue(any("test-runner.py-12-    context_call()" in ln for ln in lines))
            self.assertTrue(any("test-runner.py:13:    runner_test()" in ln for ln in lines))

    async def test_outline_skips_non_code_files_without_glob(self):
        txt_file = os.path.join(self.tmpdir, "notes.txt")
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write("class FakeNote:\n    def read(self): pass\n")
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "FakeNote", "path": "notes.txt", "mode": "outline"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("0 matches found", res.content)

    def test_role_policies_allow_search(self):
        from core.domain.policies.role_policy import role_tool_error
        from core.role_registry import BUILTIN_ROLES

        explorer = BUILTIN_ROLES["explorer"]
        worker = BUILTIN_ROLES["worker"]

        self.assertIsNone(role_tool_error(explorer, "search", is_subagent=True))
        self.assertIsNone(role_tool_error(worker, "search", is_subagent=True))
        self.assertIsNone(role_tool_error(explorer, "search", is_subagent=False))

    async def test_registered_and_executable_via_registry(self):
        self.assertIn("search", REGISTRY)
        self.assertIs(REGISTRY["search"], SearchTool)

        res = await execute_tool("search", {"query": "AppRunner", "path": self.tmpdir})
        self.assertEqual(res.status, ToolResultStatus.DONE)
        self.assertIn("AppRunner", res.content)


if __name__ == "__main__":
    unittest.main()


