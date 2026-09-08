"""Tests for johnston_cli.repl package placeholder."""
from __future__ import annotations

import io
from unittest.mock import patch

from johnston_cli.repl import start_repl


def test_start_repl_placeholder():
    f = io.StringIO()
    with patch("sys.stdout", f):
        code = start_repl()
    assert code == 0
    assert "Johnston REPL is under development" in f.getvalue()

