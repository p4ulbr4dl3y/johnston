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
    _OUTLINE_CACHE,
    SearchTool,
    _GitignoreMatcher,
    _glob_to_regex,
    _match_glob,
    _walk_filtered_list,
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
                "}\n\n"
                "const processUser = (user: User) => {\n"
                "    return user.id;\n"
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
        # New parameters
        self.assertIn("before", params["properties"])
        self.assertIn("after", params["properties"])
        self.assertIn("include_hidden", params["properties"])
        self.assertEqual(params["required"], [])

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

    def test_match_glob_recursive(self):
        # Test ** glob patterns
        self.assertTrue(_match_glob("src/main.py", "main.py", "**/*.py"))
        self.assertTrue(_match_glob("src/deep/nested/file.py", "file.py", "**/*.py"))
        self.assertTrue(_match_glob("main.py", "main.py", "**/*.py"))

    def test_glob_to_regex(self):
        # Test basic patterns
        pattern = _glob_to_regex("*.py")
        self.assertTrue(pattern.match("main.py"))
        self.assertFalse(pattern.match("main.txt"))

        # Test ** patterns
        pattern = _glob_to_regex("**/*.py")
        self.assertTrue(pattern.search("main.py"))
        self.assertTrue(pattern.search("src/main.py"))
        self.assertTrue(pattern.search("src/deep/main.py"))

    def test_outline_kotlin(self):
        kt_code = (
            "class UserService {\n"
            "    fun getUser(id: String) {}\n"
            "}\n"
            "data class Config(val name: String)\n"
            "object Singleton {}\n"
        )
        from tools.search import _outline_generic_content
        result = _outline_generic_content(kt_code)
        self.assertTrue(any("UserService" in line for line in result))
        self.assertTrue(any("getUser" in line for line in result))

    def test_outline_swift(self):
        swift_code = (
            "class ViewController {\n"
            "    func viewDidLoad() {}\n"
            "}\n"
            "struct UserModel: Codable {}\n"
            "protocol Configurable {}\n"
            "extension String {}\n"
            "enum Status {}\n"
        )
        from tools.search import _outline_generic_content
        result = _outline_generic_content(swift_code)
        self.assertTrue(any("ViewController" in line for line in result))
        self.assertTrue(any("viewDidLoad" in line for line in result))
        self.assertTrue(any("UserModel" in line for line in result))
        self.assertTrue(any("Configurable" in line for line in result))
        self.assertTrue(any("extension String" in line for line in result))
        self.assertTrue(any("enum Status" in line for line in result))

    def test_outline_scala(self):
        scala_code = (
            "class Server {\n"
            "    def start(): Unit = {}\n"
            "}\n"
            "object MainApp {}\n"
            "trait Configurable {}\n"
        )
        from tools.search import _outline_generic_content
        result = _outline_generic_content(scala_code)
        self.assertTrue(any("Server" in line for line in result))
        self.assertTrue(any("start" in line for line in result))
        self.assertTrue(any("MainApp" in line for line in result))
        self.assertTrue(any("Configurable" in line for line in result))

    def test_outline_arrow_functions(self):
        ts_code = "const handler = (e) => { return e; }\nlet process = (x) => x + 1\n"
        from tools.search import _outline_generic_content
        result = _outline_generic_content(ts_code)
        self.assertTrue(any("handler" in line for line in result))
        self.assertTrue(any("process" in line for line in result))

    def test_outline_rust_impl(self):
        rs_code = "impl Data {\n    fn new() -> Self {}\n}\nmod utils {}\n"
        from tools.search import _outline_generic_content
        result = _outline_generic_content(rs_code)
        self.assertTrue(any("impl Data" in line for line in result))
        self.assertTrue(any("mod utils" in line for line in result))

    def test_outline_go_type(self):
        go_code = "type ServerConfig struct {\n    Port int\n}\ntype Handler interface {}\n"
        from tools.search import _outline_generic_content
        result = _outline_generic_content(go_code)
        self.assertTrue(any("ServerConfig" in line for line in result))
        self.assertTrue(any("Handler" in line for line in result))

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

    async def test_content_search_before_after(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Test asymmetric context
        res = await self.tool.execute(
            {"query": "def run", "path": "main.py", "before": 2, "after": 1},
            ctx=ctx,
        )
        self.assertIn("main.py:7:", res.content)
        # Should have 2 lines before and 1 after
        self.assertIn("main.py-5-", res.content)
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

    async def test_filename_mode_with_ripgrep(self):
        if not shutil.which("rg"):
            self.skipTest("rg binary not installed")
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "helper", "mode": "filename"}, ctx=ctx)
        self.assertIn("helper.py", res.content)

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
        # Arrow function detection
        self.assertIn("processUser", res.content)

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
        """Integration test for Go, Rust, Kotlin, Swift, Scala outline via tool execute."""
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
                "impl EventQueue {\n"
                "    pub fn new() -> Self {}\n"
                "}\n"
            )

        # Kotlin
        kt_file = os.path.join(self.tmpdir, "Main.kt")
        with open(kt_file, "w") as f:
            f.write(
                "class UserService {\n"
                "    fun getUser(id: String): User {}\n"
                "}\n"
                "data class UserConfig(val name: String)\n"
            )

        # Swift
        swift_file = os.path.join(self.tmpdir, "Service.swift")
        with open(swift_file, "w") as f:
            f.write(
                "class ViewController: UIViewController {\n"
                "    func viewDidLoad() {}\n"
                "}\n"
                "struct UserModel: Codable {}\n"
            )

        # Scala
        scala_file = os.path.join(self.tmpdir, "App.scala")
        with open(scala_file, "w") as f:
            f.write(
                "class Server {\n"
                "    def start(): Unit = {}\n"
                "}\n"
                "object MainApp extends App {}\n"
                "trait Configurable {}\n"
            )

        ctx = ToolContext(cwd=self.tmpdir)

        res_go = await self.tool.execute({"query": "*", "path": "server.go", "mode": "outline"}, ctx=ctx)
        self.assertIn("HandleRequest", res_go.content)
        self.assertIn("ServerConfig", res_go.content)

        res_rs = await self.tool.execute({"query": "*", "path": "lib.rs", "mode": "outline"}, ctx=ctx)
        self.assertIn("process_event", res_rs.content)
        self.assertIn("EventQueue", res_rs.content)
        self.assertIn("impl", res_rs.content)

        res_kt = await self.tool.execute({"query": "*", "path": "Main.kt", "mode": "outline"}, ctx=ctx)
        self.assertIn("UserService", res_kt.content)
        self.assertIn("getUser", res_kt.content)

        res_swift = await self.tool.execute({"query": "*", "path": "Service.swift", "mode": "outline"}, ctx=ctx)
        self.assertIn("ViewController", res_swift.content)
        self.assertIn("viewDidLoad", res_swift.content)

        res_scala = await self.tool.execute({"query": "*", "path": "App.scala", "mode": "outline"}, ctx=ctx)
        self.assertIn("Server", res_scala.content)
        self.assertIn("start", res_scala.content)

    async def test_ripgrep_failure_falls_back_to_python(self):
        ctx = ToolContext(cwd=self.tmpdir)
        # Mock ripgrep raising an exception to test graceful python fallback
        with patch("subprocess.Popen", side_effect=OSError("rg failed")):
            res = await self.tool.execute({"query": "AppRunner", "path": "."}, ctx=ctx)
            self.assertEqual(res.status, ToolResultStatus.DONE)
            self.assertIn("AppRunner", res.content)

    def test_ripgrep_line_parsing_windows_and_hyphens(self):
        from tools.search import _search_content_ripgrep

        mock_lines = [
            "C:\\repo\\main.py\x0010:def hello():\n",
            "test-runner.py\x0012-    context_call()\n",
            "test-runner.py\x0013:    runner_test()\n",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(mock_lines)
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ("", "")

        with patch("subprocess.Popen", return_value=mock_proc):
            lines, count, files_count = _search_content_ripgrep(
                target_path=".", query="test", cwd="C:\\repo"
            )
            self.assertEqual(count, 2)
            self.assertEqual(files_count, 2)
            self.assertTrue(any("main.py:10:def hello():" in line for line in lines))
            self.assertTrue(any("test-runner.py-12-    context_call()" in line for line in lines))
            self.assertTrue(any("test-runner.py:13:    runner_test():" in line for line in lines))

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

    async def test_include_hidden_files(self):
        # Create a hidden file
        hidden_file = os.path.join(self.tmpdir, ".hidden_config.py")
        with open(hidden_file, "w") as f:
            f.write("SECRET_KEY = 'abc123'\n")

        ctx = ToolContext(cwd=self.tmpdir)
        # Without include_hidden
        res1 = await self.tool.execute({"query": "SECRET_KEY"}, ctx=ctx)
        self.assertNotIn(".hidden_config.py", res1.content)

        # With include_hidden
        res2 = await self.tool.execute({"query": "SECRET_KEY", "include_hidden": True}, ctx=ctx)
        self.assertIn(".hidden_config.py", res2.content)

    async def test_elapsed_time_in_header(self):
        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "AppRunner"}, ctx=ctx)
        self.assertIn("elapsed_ms=", res.content)

    async def test_parallel_outline_processing(self):
        # Create many files to trigger parallel processing
        for i in range(25):
            fpath = os.path.join(self.tmpdir, f"file_{i:03d}.py")
            with open(fpath, "w") as f:
                f.write(f"def function_{i}():\n    return {i}\n")

        ctx = ToolContext(cwd=self.tmpdir)
        res = await self.tool.execute({"query": "*", "mode": "outline", "glob": "file_*.py"}, ctx=ctx)
        self.assertEqual(res.status, ToolResultStatus.DONE)
        # Should find all functions
        self.assertIn("function_000", res.content)
        self.assertIn("function_024", res.content)

    async def test_parallel_content_search(self):
        # Create many files to trigger parallel processing
        for i in range(25):
            fpath = os.path.join(self.tmpdir, f"search_{i:03d}.txt")
            with open(fpath, "w") as f:
                f.write(f"This is test content {i}\n")

        ctx = ToolContext(cwd=self.tmpdir)
        with patch("shutil.which", return_value=None):  # Force Python fallback
            res = await self.tool.execute({"query": "test content"}, ctx=ctx)
            self.assertEqual(res.status, ToolResultStatus.DONE)
            self.assertIn("search_000.txt", res.content)
            self.assertIn("search_024.txt", res.content)


class TestGitignoreMatcher(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_gitignore(self):
        # Create .gitignore
        gitignore = os.path.join(self.tmpdir, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("*.log\n")
            f.write("build/\n")
            f.write("!important.log\n")

        matcher = _GitignoreMatcher.load_from_root(self.tmpdir)
        self.assertIsNotNone(matcher)

        # Test ignored patterns
        self.assertTrue(matcher.is_ignored("test.log"))
        self.assertTrue(matcher.is_ignored("build/output.txt"))
        self.assertTrue(matcher.is_ignored("src/debug.log"))

        # Test negation
        self.assertFalse(matcher.is_ignored("important.log"))

        # Test non-ignored
        self.assertFalse(matcher.is_ignored("main.py"))
        self.assertFalse(matcher.is_ignored("src/main.py"))

    def test_recursive_gitignore(self):
        # Create nested .gitignore files
        root_gitignore = os.path.join(self.tmpdir, ".gitignore")
        with open(root_gitignore, "w") as f:
            f.write("*.tmp\n")

        sub_dir = os.path.join(self.tmpdir, "sub")
        os.makedirs(sub_dir)
        sub_gitignore = os.path.join(sub_dir, ".gitignore")
        with open(sub_gitignore, "w") as f:
            f.write("*.cache\n")

        matcher = _GitignoreMatcher.load_from_root(self.tmpdir)
        self.assertIsNotNone(matcher)

        # Root patterns apply everywhere
        self.assertTrue(matcher.is_ignored("file.tmp"))
        self.assertTrue(matcher.is_ignored("sub/file.tmp"))

        # Sub-directory patterns
        self.assertTrue(matcher.is_ignored("sub/file.cache"))

    def test_double_star_patterns(self):
        gitignore = os.path.join(self.tmpdir, ".gitignore")
        with open(gitignore, "w") as f:
            f.write("**/test_*.py\n")
            f.write("src/**/*.bak\n")

        matcher = _GitignoreMatcher.load_from_root(self.tmpdir)
        self.assertIsNotNone(matcher)

        # ** matches any depth
        self.assertTrue(matcher.is_ignored("test_main.py"))
        self.assertTrue(matcher.is_ignored("src/test_main.py"))
        self.assertTrue(matcher.is_ignored("src/deep/test_main.py"))

        self.assertTrue(matcher.is_ignored("src/file.bak"))
        self.assertTrue(matcher.is_ignored("src/sub/file.bak"))
        self.assertTrue(matcher.is_ignored("src/sub/deep/file.bak"))


class TestLRUCache(unittest.TestCase):
    """Tests for outline LRU cache with mtime invalidation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _OUTLINE_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _OUTLINE_CACHE.clear()

    def test_cache_hit(self):
        """Test that repeated outline calls use cache."""
        test_file = os.path.join(self.tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("def func1():\n    pass\n")

        from tools.search import _outline_file

        # First call
        result1 = _outline_file(test_file, self.tmpdir, "*", None, use_cache=True)
        self.assertIsNotNone(result1)

        # Second call should use cache
        result2 = _outline_file(test_file, self.tmpdir, "*", None, use_cache=True)
        self.assertIsNotNone(result2)
        self.assertEqual(result1[1], result2[1])

    def test_cache_invalidation(self):
        """Test that cache invalidates on mtime change."""
        test_file = os.path.join(self.tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("def func1():\n    pass\n")

        from tools.search import _outline_file

        # First call
        result1 = _outline_file(test_file, self.tmpdir, "*", None, use_cache=True)
        self.assertIsNotNone(result1)
        self.assertTrue(any("func1" in line for line in result1[1]))

        # Modify file
        import time

        time.sleep(0.1)  # Ensure mtime changes
        with open(test_file, "w") as f:
            f.write("def func2():\n    pass\n")

        # Should get updated result
        result2 = _outline_file(test_file, self.tmpdir, "*", None, use_cache=True)
        self.assertIsNotNone(result2)
        self.assertTrue(any("func2" in line for line in result2[1]))

    def test_cache_clear(self):
        """Test cache clearing."""
        test_file = os.path.join(self.tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("def func1():\n    pass\n")

        from tools.search import _outline_file

        _outline_file(test_file, self.tmpdir, "*", None, use_cache=True)
        self.assertGreater(len(_OUTLINE_CACHE._cache), 0)

        _OUTLINE_CACHE.clear()
        self.assertEqual(len(_OUTLINE_CACHE._cache), 0)


class TestGeneratorWalk(unittest.TestCase):
    """Tests for generator-based file walk."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generator_yields_files(self):
        """Test that generator yields all files."""
        for i in range(5):
            with open(os.path.join(self.tmpdir, f"file{i}.py"), "w") as f:
                f.write("pass\n")

        files = list(_walk_filtered_list(self.tmpdir))
        self.assertEqual(len(files), 5)

    def test_early_termination(self):
        """Test that generator supports early termination."""
        from tools.search import _walk_filtered

        for i in range(10):
            with open(os.path.join(self.tmpdir, f"file{i}.py"), "w") as f:
                f.write("pass\n")

        count = 0
        for f in _walk_filtered(self.tmpdir):
            count += 1
            if count >= 3:
                break

        self.assertEqual(count, 3)


class TestProgressCallback(unittest.TestCase):
    """Tests for progress callback functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_progress_events_emitted(self):
        """Test that progress events are emitted during outline search."""
        for i in range(30):
            with open(os.path.join(self.tmpdir, f"file{i:03d}.py"), "w") as f:
                f.write(f"def func{i}():\n    pass\n")

        progress_events = []

        def callback(event):
            progress_events.append(event)

        result = search_sync(
            query="*",
            path=self.tmpdir,
            cwd=self.tmpdir,
            mode="outline",
            glob_pattern="*.py",
            max_results=500,
            progress_callback=callback,
        )

        self.assertEqual(result.status.value, "done")
        self.assertGreater(len(progress_events), 0)

    def test_start_and_done_events(self):
        """Test that start and done events are always emitted."""
        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("def func():\n    pass\n")

        progress_events = []

        def callback(event):
            progress_events.append(event)

        search_sync(
            query="func",
            path=self.tmpdir,
            cwd=self.tmpdir,
            mode="content",
            progress_callback=callback,
        )

        stages = [e.get("stage") for e in progress_events]
        self.assertIn("start", stages)
        self.assertIn("done", stages)


class TestTreeSitter(unittest.TestCase):
    """Tests for tree-sitter integration (optional dependency)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tree_sitter_available(self):
        """Test that tree-sitter availability is detected."""
        from tools.search import TREE_SITTER_AVAILABLE
        # Just check it's a boolean
        self.assertIsInstance(TREE_SITTER_AVAILABLE, bool)

    def test_python_perfect_accuracy(self):
        """Test tree-sitter ignores comments and strings in Python."""
        from tools.search import TREE_SITTER_AVAILABLE
        if not TREE_SITTER_AVAILABLE:
            self.skipTest("Tree-sitter not available")

        with open(os.path.join(self.tmpdir, "test.py"), "w") as f:
            f.write("""
# Comment: class FakeClass
\"\"\"Docstring: class AnotherFake\"\"\"
class RealClass:
    def real_method(self):
        pass
x = "string: class YetAnotherFake"
""")

        result = search_sync(
            query="*",
            path=self.tmpdir,
            cwd=self.tmpdir,
            mode="outline",
            glob_pattern="*.py",
        )

        self.assertIn("RealClass", result.content)
        self.assertIn("real_method", result.content)
        self.assertNotIn("FakeClass", result.content)
        self.assertNotIn("AnotherFake", result.content)
        self.assertNotIn("YetAnotherFake", result.content)

    def test_javascript_perfect_accuracy(self):
        """Test tree-sitter ignores comments and strings in JavaScript."""
        from tools.search import TREE_SITTER_AVAILABLE
        if not TREE_SITTER_AVAILABLE:
            self.skipTest("Tree-sitter not available")

        with open(os.path.join(self.tmpdir, "test.js"), "w") as f:
            f.write("""
// Comment: class FakeClass
/* Block comment: class AnotherFake */
function realFunc() {}
class RealClass {}
const x = "string: class YetAnotherFake";
""")

        result = search_sync(
            query="*",
            path=self.tmpdir,
            cwd=self.tmpdir,
            mode="outline",
            glob_pattern="*.js",
        )

        self.assertIn("realFunc", result.content)
        self.assertIn("RealClass", result.content)
        self.assertNotIn("FakeClass", result.content)
        self.assertNotIn("AnotherFake", result.content)

    def test_typescript_perfect_accuracy(self):
        """Test tree-sitter ignores comments and strings in TypeScript."""
        from tools.search import TREE_SITTER_AVAILABLE
        if not TREE_SITTER_AVAILABLE:
            self.skipTest("Tree-sitter not available")

        with open(os.path.join(self.tmpdir, "test.ts"), "w") as f:
            f.write("""
// Comment: class FakeClass
interface RealInterface {}
class RealClass {}
export function helper() {}
""")

        result = search_sync(
            query="*",
            path=self.tmpdir,
            cwd=self.tmpdir,
            mode="outline",
            glob_pattern="*.ts",
        )

        self.assertIn("RealClass", result.content)
        self.assertIn("helper", result.content)
        self.assertNotIn("FakeClass", result.content)


if __name__ == "__main__":
    unittest.main()
