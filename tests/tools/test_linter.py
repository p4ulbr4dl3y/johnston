import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.linters_manager import LintersManager, _clean_output, _exec_cmd


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

    @patch("core.linters_manager.LintersManager.is_available", return_value=True)
    async def test_non_existent_file(self, _avail):
        path = os.path.join(self.temp_dir.name, "non_existent.py")
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        result = await lm.run_for(path)
        self.assertEqual(result, "")

    @patch("core.linters_manager._exec_cmd")
    @patch("core.linters_manager.LintersManager.is_available", return_value=True)
    async def test_python_linter_error_reported(self, _avail, mock_exec_cmd):
        mock_exec_cmd.return_value = "file.py:1:1: F401 'os' imported but unused"
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        lm.load_linters = MagicMock(return_value=[fake_linter("python")])
        with patch.object(
            lm, "render_cmd", side_effect=lambda lint, path: [c.replace("{file}", path) for c in lint["cmd"]]
        ):
            py_file = os.path.join(self.temp_dir.name, "test.py")
            with open(py_file, "w") as f:
                f.write("import os\n")
            result = await lm.run_for(py_file)
        mock_exec_cmd.assert_called_once()
        cmd_arg = mock_exec_cmd.call_args[0][0]
        self.assertEqual(cmd_arg[:3], ["ruff", "check", "--select"])
        self.assertEqual(cmd_arg[3], "E9,F")
        self.assertIn("F401", result)

    @patch("core.linters_manager._exec_cmd")
    async def test_no_matching_linter(self, mock_exec_cmd):
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        lm.get_for_extension = MagicMock(return_value=[])
        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")
        result = await lm.run_for(py_file)
        self.assertEqual(result, "")
        mock_exec_cmd.assert_not_called()

    @patch("core.linters_manager._exec_cmd")
    async def test_multiple_matching_linters_aggregate(self, mock_exec_cmd):
        mock_exec_cmd.side_effect = ["one error", "two error"]
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        lm.get_for_extension = MagicMock(
            return_value=[fake_linter("ruff", exts=[".py"]), fake_linter("mypy", exts=[".py"])]
        )
        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")
        result = await lm.run_for(py_file)
        self.assertIn("one error", result)
        self.assertIn("two error", result)

    @patch("core.linters_manager._exec_cmd")
    async def test_clean_lines_filtering_all_filtered(self, mock_exec_cmd):
        mock_exec_cmd.return_value = "Downloading dependency...\nBuilding wheel...\nAudited 5 packages"
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        lm.get_for_extension = MagicMock(return_value=[fake_linter("ruff")])
        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")
        result = await lm.run_for(py_file)
        self.assertEqual(result, "")

    @patch("core.linters_manager._exec_cmd")
    async def test_line_truncation_over_10_lines(self, mock_exec_cmd):
        many_errors = "\n".join([f"file.py:{i}:1: E101 error {i}" for i in range(15)])
        mock_exec_cmd.return_value = many_errors
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        lm.get_for_extension = MagicMock(return_value=[fake_linter("ruff")])
        py_file = os.path.join(self.temp_dir.name, "test.py")
        with open(py_file, "w") as f:
            f.write("x = 1\n")
        result = await lm.run_for(py_file)
        self.assertIn("... (5 more lines)", result)

    async def test_exec_cmd_nonzero_exit(self):
        output = await _exec_cmd([sys.executable, "-c", "import sys; print('some error'); sys.exit(1)"])
        self.assertEqual(output, "some error")

    async def test_exec_cmd_zero_exit(self):
        output = await _exec_cmd([sys.executable, "-c", "print('normal output')"])
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

    def test_clean_output(self):
        text = "Downloading x\nreal error\nBuilding y"
        self.assertIn("real error", _clean_output(text))
        self.assertNotIn("Downloading", _clean_output(text))

    def test_presets_disabled_by_default(self):
        lm = LintersManager(config_file=os.path.join(self.temp_dir.name, "linters.json"))
        for lint in lm.load_linters():
            self.assertFalse(
                bool(lint.get("enabled")), f"preset '{lint.get('name')}' should be disabled by default"
            )

    def test_preset_enabled_via_config(self):
        cfg = os.path.join(self.temp_dir.name, "linters.json")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write('{"linters": {"python": {"enabled": true}}}')
        lm = LintersManager(config_file=cfg)
        python = next(lint for lint in lm.load_linters() if lint.get("name") == "python")
        self.assertTrue(python.get("enabled"))

    def test_cached_which(self):
        from core.linters_manager import _cached_which

        _cached_which.cache_clear()
        res = _cached_which("python3") or _cached_which("python") or _cached_which("ls")
        self.assertIsNotNone(res)


if __name__ == "__main__":
    unittest.main()
