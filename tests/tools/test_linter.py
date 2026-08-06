import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.linter import _cached_which, _exec_cmd, run_linter


def fake_linter(name="ruff", exts=None, cmd=None, enabled=True, available=True):
    return {
        "name": name,
        "label": name,
        "extensions": exts or [".py"],
        "cmd": cmd or ["ruff", "check", "--select", "E9,F", "{file}"],
        "enabled": enabled,
        "install": "system",
    }


class TestLinter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        import tools.linter as linter_mod
        linter_mod._linter_mgr_cache = None

    def test_cached_which(self):
        _cached_which.cache_clear()
        res = _cached_which("python3") or _cached_which("python") or _cached_which("ls")
        self.assertIsNotNone(res)
        res_none = _cached_which("non_existent_binary_xyz_12345")
        self.assertIsNone(res_none)

    async def test_non_existent_file(self):
        result = await run_linter(os.path.join(self.temp_dir.name, "non_existent.py"))
        self.assertEqual(result, "")

    @patch("tools.linter._exec_cmd")
    async def test_python_linter_error_reported(self, mock_exec_cmd):
        mock_exec_cmd.return_value = "file.py:1:1: F401 'os' imported but unused"
        fake = fake_linter("python")
        mgr = MagicMock()
        mgr.get_for_extension.return_value = [fake]
        mgr.render_cmd.side_effect = lambda lint, path: [c.replace("{file}", path) for c in lint["cmd"]]

        with patch("tools.linter.get_linters_manager", return_value=mgr):
            py_file = os.path.join(self.temp_dir.name, "test.py")
            with open(py_file, "w") as f:
                f.write("import os\n")
            result = await run_linter(py_file)
        mock_exec_cmd.assert_called_once()
        cmd_arg = mock_exec_cmd.call_args[0][0]
        self.assertEqual(cmd_arg[:3], ["ruff", "check", "--select"])
        self.assertEqual(cmd_arg[3], "E9,F")
        self.assertIn("F401", result)

    @patch("tools.linter._exec_cmd")
    async def test_no_matching_linter(self, mock_exec_cmd):
        mgr = MagicMock()
        mgr.get_for_extension.return_value = []

        with patch("tools.linter.get_linters_manager", return_value=mgr):
            py_file = os.path.join(self.temp_dir.name, "test.py")
            with open(py_file, "w") as f:
                f.write("x = 1\n")
            result = await run_linter(py_file)
        self.assertEqual(result, "")
        mock_exec_cmd.assert_not_called()

    async def test_linter_not_available_skipped(self):
        mgr = MagicMock()
        mgr.get_for_extension.return_value = []

        with patch("tools.linter.get_linters_manager", return_value=mgr):
            py_file = os.path.join(self.temp_dir.name, "test.py")
            with open(py_file, "w") as f:
                f.write("x = 1\n")
            result = await run_linter(py_file)
        self.assertEqual(result, "")

    @patch("tools.linter._exec_cmd")
    async def test_multiple_matching_linters_aggregate(self, mock_exec_cmd):
        mock_exec_cmd.side_effect = ["one error", "two error"]
        fake1 = fake_linter("ruff", exts=[".py"])
        fake2 = fake_linter("mypy", exts=[".py"])
        mgr = MagicMock()
        mgr.get_for_extension.return_value = [fake1, fake2]

        with patch("tools.linter.get_linters_manager", return_value=mgr):
            py_file = os.path.join(self.temp_dir.name, "test.py")
            with open(py_file, "w") as f:
                f.write("x = 1\n")
            result = await run_linter(py_file)
        self.assertIn("one error", result)
        self.assertIn("two error", result)

    @patch("tools.linter._exec_cmd")
    async def test_clean_lines_filtering_all_filtered(self, mock_exec_cmd):
        mock_exec_cmd.return_value = "Downloading dependency...\nBuilding wheel...\nAudited 5 packages"
        fake = fake_linter("ruff")
        mgr = MagicMock()
        mgr.get_for_extension.return_value = [fake]

        with patch("tools.linter.get_linters_manager", return_value=mgr):
            py_file = os.path.join(self.temp_dir.name, "test.py")
            with open(py_file, "w") as f:
                f.write("x = 1\n")
            result = await run_linter(py_file)
        self.assertEqual(result, "")

    @patch("tools.linter._exec_cmd")
    async def test_line_truncation_over_10_lines(self, mock_exec_cmd):
        many_errors = "\n".join([f"file.py:{i}:1: E101 error {i}" for i in range(15)])
        mock_exec_cmd.return_value = many_errors
        fake = fake_linter("ruff")
        mgr = MagicMock()
        mgr.get_for_extension.return_value = [fake]

        with patch("tools.linter.get_linters_manager", return_value=mgr):
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
