"""Tests for johnston_cli package entrypoints and dispatching."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from johnston_cli.entrypoint import build_parser, main, main_j, main_johnston
from johnston_cli.repl import start_repl


class TestJohnstonCLI(unittest.TestCase):
    def test_build_parser_prog_variants(self):
        p_j = build_parser(prog="j")
        self.assertEqual(p_j.prog, "j")
        self.assertEqual(p_j.description, "Johnston Interactive Agent CLI")

        p_johnston = build_parser(prog="johnston")
        self.assertEqual(p_johnston.prog, "johnston")
        self.assertEqual(p_johnston.description, "Johnston Coding Agent (TUI & CLI)")

    def test_start_repl(self):
        code = start_repl("hello")
        self.assertEqual(code, 0)

    def test_main_j_no_args_starts_repl(self):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("johnston_cli.entrypoint.start_repl", return_value=0) as mock_repl:
                code = main_j([])
                self.assertEqual(code, 0)
                mock_repl.assert_called_once()

    def test_main_j_with_positional_prompt(self):
        with patch("johnston_cli.entrypoint.run_headless", return_value=0) as mock_run:
            code = main_j(["fix", "this", "bug"])
            self.assertEqual(code, 0)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertEqual(args.headless_prompt, "fix this bug")

    def test_main_j_subcommand_dispatch(self):
        with patch("johnston_cli.entrypoint.run_doctor", return_value=0) as mock_doc:
            code = main_j(["doctor"])
            self.assertEqual(code, 0)
            mock_doc.assert_called_once()

    def test_main_johnston_subcommand_dispatch(self):
        with patch("johnston_cli.entrypoint.run_doctor", return_value=0) as mock_doc:
            code = main_johnston(["doctor"])
            self.assertEqual(code, 0)
            mock_doc.assert_called_once()

    def test_main_default_delegates(self):
        with patch("johnston_cli.entrypoint.main_johnston", return_value=0) as mock_mj:
            code = main(["doctor"])
            self.assertEqual(code, 0)
            mock_mj.assert_called_once_with(["doctor"])


if __name__ == "__main__":
    unittest.main()
