import os
import unittest
from unittest.mock import MagicMock, patch

from core.application.permission.permission_manager import PermissionManager
from core.interfaces.cli.commands.run_cmd import run_headless
from core.interfaces.cli.entrypoint import build_parser, main


class TestCliWorkspaceFlag(unittest.TestCase):
    def setUp(self):
        self.pm = PermissionManager.configure_instance()

    def tearDown(self):
        self.pm.workspace_roots = [os.path.realpath(os.getcwd())]
        self.pm.clear_session_overrides()

    def test_parser_workspace_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-w", "/path/one", "--workspace", "/path/two"])
        self.assertEqual(args.workspace, ["/path/one", "/path/two"])

    def test_run_subparser_workspace_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "hello", "-w", "/sub/one", "--workspace", "/sub/two"])
        self.assertEqual(args.workspace, ["/sub/one", "/sub/two"])

    def test_main_registers_workspace_roots(self):
        ws1 = os.path.realpath("/tmp/test_ws1")
        ws2 = os.path.realpath("/tmp/test_ws2")

        with patch("app.JohnstonApp") as mock_app_cls:
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app
            with self.assertRaises(SystemExit) as ctx:
                main(["-w", ws1, "--workspace", ws2])
            self.assertEqual(ctx.exception.code, 0)

        roots = self.pm.get_workspace_roots()
        self.assertIn(ws1, roots)
        self.assertIn(ws2, roots)

    def test_run_headless_registers_workspace_roots(self):
        ws = os.path.realpath("/tmp/test_headless_ws")
        parser = build_parser()
        args = parser.parse_args(["run", "test prompt", "-w", ws])

        with patch("core.interfaces.cli.commands.run_cmd.run_headless_async") as mock_async:
            mock_async.return_value = 0
            code = run_headless(args)
            self.assertEqual(code, 0)

        roots = self.pm.get_workspace_roots()
        self.assertIn(ws, roots)
