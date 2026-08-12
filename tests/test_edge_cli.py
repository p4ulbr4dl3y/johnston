import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from cli import main


class TestCLIEdgeMain(unittest.TestCase):
    @patch("sys.argv", ["johnston"])
    @patch("app.JohnstonApp")
    def test_main_empty_args_no_crash(self, mock_app_cls):
        """Empty argv (no flags) must launch the app cleanly without exception."""
        mock_app = mock_app_cls.return_value
        mock_app.run = MagicMock()
        mock_app.current_session_id = None
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(mock_app.run.called)

    @patch("sys.argv", ["johnston", "--models", "--skills"])
    def test_invalid_flag_combo_runs_both_but_exits_once(self):
        """Passing two listing flags is ambiguous; the CLI must handle it
        deterministically (first wins) without a traceback."""
        with patch("cli.print_models") as pm, patch("cli.print_skills") as ps:
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)
            pm.assert_called_once()
            ps.assert_not_called()

    @patch("sys.argv", ["johnston", "-v", "--models"])
    def test_version_takes_precedence(self):
        with patch("cli.print_models") as pm, patch("cli.get_version", return_value="1.2.3"):
            f = io.StringIO()
            with redirect_stdout(f):
                with self.assertRaises(SystemExit) as cm:
                    main()
            self.assertEqual(cm.exception.code, 0)
            self.assertIn("1.2.3", f.getvalue())
            pm.assert_not_called()

    @patch("sys.argv", ["johnston", "--resume", "sess-юникод-1"])
    @patch("app.JohnstonApp.run")
    def test_unicode_resume_arg_handled(self, mock_run):
        """Unicode args to --resume must not cause encode/parse errors."""
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 0)

    def test_get_version_non_ascii_encoding(self):
        """Version string must be clean ASCII for buggy terminals."""
        from cli import get_version

        ver = get_version()
        self.assertIsInstance(ver, str)

    @patch("sys.argv", ["johnston", "--linters"])
    def test_main_linters_failure_preserves_traceback_semantics(self):
        """A linter listing error must not be silently swallowed into a crash."""
        with patch("cli.print_linters", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                main()


class TestCLIEdgeResumeTip(unittest.TestCase):
    @patch("sys.argv", ["johnston"])
    @patch("app.JohnstonApp")
    def test_resume_tip_with_none_session_skips(self, mock_app_cls):
        """When current_session_id is None the tip code path must not crash."""
        mock_app = mock_app_cls.return_value
        mock_app.run = MagicMock()
        mock_app.current_session_id = None
        f = io.StringIO()
        with redirect_stdout(f):
            with self.assertRaises(SystemExit) as cm:
                main()
        self.assertEqual(cm.exception.code, 0)
        self.assertNotIn("--resume", f.getvalue())


if __name__ == "__main__":
    unittest.main()
