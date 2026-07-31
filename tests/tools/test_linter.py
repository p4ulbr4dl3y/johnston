import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.linter import _cached_which, _exec_cmd, run_linter


class TestLinter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_cached_which(self):
        _cached_which.cache_clear()
        res = _cached_which("python3") or _cached_which("python") or _cached_which("ls")
        self.assertIsNotNone(res)
        res_none = _cached_which("non_existent_binary_xyz_12345")
        self.assertIsNone(res_none)

    async def test_non_existent_file(self):
        result = await run_linter(os.path.join(self.temp_dir.name, "non_existent.py"))
        self.assertEqual(result, "")

    @patch("tools.linter._cached_which")
    @patch("tools.linter._exec_cmd")
    async def test_ruff_fallback_to_uv(self, mock_exec_cmd, mock_which):
        def which_side_effect(cmd):
            if cmd == "ruff":
                return None
            if cmd == "uv":
                return "/usr/bin/uv"
            return None

        mock_which.side_effect = which_side_effect
        mock_exec_cmd.return_value = "file.py:1:1: F401 'os' imported but unused"

        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("import os\n")

        result = await run_linter(py_file)
        mock_exec_cmd.assert_called_once()
        cmd_arg = mock_exec_cmd.call_args[0][0]
        self.assertEqual(cmd_arg[:3], ["uv", "run", "--no-sync"])
        self.assertIn("F401", result)

    @patch("tools.linter._cached_which", return_value=None)
    async def test_no_linter_available(self, mock_which):
        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("import os\n")

        result = await run_linter(py_file)
        self.assertEqual(result, "")

    @patch("tools.linter._cached_which")
    @patch("tools.linter._exec_cmd")
    async def test_biome_linter_supported_extensions(self, mock_exec_cmd, mock_which):
        mock_which.side_effect = lambda cmd: "/usr/bin/biome" if cmd == "biome" else None
        mock_exec_cmd.return_value = "test.ts:1:1 error linting error"

        for ext in (".ts", ".tsx", ".js", ".jsx", ".json"):
            file_path = os.path.join(self.temp_dir.name, f"test{ext}")
            with open(file_path, "w") as f:
                f.write("{}\n")

            result = await run_linter(file_path)
            self.assertIn("linting error", result)

    @patch("tools.linter._cached_which", return_value=None)
    async def test_ts_file_without_biome(self, mock_which):
        ts_file = os.path.join(self.temp_dir.name, "test.ts")
        with open(ts_file, "w") as f:
            f.write("const x = 1;\n")

        result = await run_linter(ts_file)
        self.assertEqual(result, "")

    @patch("tools.linter._cached_which", return_value="/usr/bin/ruff")
    @patch("tools.linter._exec_cmd")
    async def test_clean_lines_filtering_all_filtered(self, mock_exec_cmd, mock_which):
        mock_exec_cmd.return_value = "Downloading dependency...\nBuilding wheel...\nAudited 5 packages"
        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")

        result = await run_linter(py_file)
        self.assertEqual(result, "")

    @patch("tools.linter._cached_which", return_value="/usr/bin/ruff")
    @patch("tools.linter._exec_cmd")
    async def test_line_truncation_over_10_lines(self, mock_exec_cmd, mock_which):
        many_errors = "\n".join([f"file.py:{i}:1: E101 error {i}" for i in range(15)])
        mock_exec_cmd.return_value = many_errors

        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")

        result = await run_linter(py_file)
        self.assertIn("... (5 more lines)", result)

    async def test_exec_cmd_nonzero_exit(self):
        output = await _exec_cmd(["python3", "-c", "import sys; print('some error'); sys.exit(1)"])
        self.assertEqual(output, "some error")

    async def test_exec_cmd_zero_exit(self):
        output = await _exec_cmd(["python3", "-c", "print('normal output')"])
        self.assertIsNone(output)

    @patch("asyncio.wait_for", side_effect=asyncio.TimeoutError)
    @patch("asyncio.create_subprocess_exec")
    async def test_exec_cmd_timeout(self, mock_create_proc, mock_wait_for):
        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_create_proc.return_value = mock_proc

        result = await _exec_cmd(["sleep", "10"])
        self.assertIsNone(result)
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once()

    @patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("Subprocess error"))
    async def test_exec_cmd_exception(self, mock_create_proc):
        result = await _exec_cmd(["some_cmd"])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
