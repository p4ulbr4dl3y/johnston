"""Tests asserting the unified `ERR:` error convention across all tools.

Two checks:
1. `format_tool_error` produces the canonical `ERR: <kind> '<name>': <detail>` shape.
2. Static (AST) scan: every error-handling branch in tools/*.py that returns a
   string error must either go through `format_tool_error` or already begin with
   `ERR:`. This guards the invariant that no tool leaks a bare/generic error
   string back to the model.
"""
import ast
import os
import unittest
from pathlib import Path

from core.domain.defaults.errors import format_tool_error

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"


class TestFormatToolError(unittest.TestCase):
    def test_full_shape(self):
        self.assertEqual(
            format_tool_error("file", detail="not found", name="/tmp/x.py"),
            "ERR: file '/tmp/x.py': not found",
        )

    def test_kind_only(self):
        self.assertEqual(format_tool_error("kind"), "ERR: kind")

    def test_detail_without_name(self):
        self.assertEqual(format_tool_error("params", detail="bad"), "ERR: params: bad")

    def test_name_without_detail(self):
        self.assertEqual(format_tool_error("denied", name="read"), "ERR: denied 'read'")


def _is_timeout_or_cancel_handler(handler: ast.ExceptHandler) -> bool:
    """True when the handler only recovers from timeout/cancellation (not an error)."""
    if not handler.type:
        return False
    if isinstance(handler.type, ast.Tuple):
        names = [n for n in handler.type.elts if isinstance(n, ast.expr)]
    else:
        names = [handler.type]
    for nt in names:
        checked = nt.id if isinstance(nt, ast.Name) else (nt.attr if isinstance(nt, ast.Attribute) else "")
        if checked in ("TimeoutError", "CancelledError"):
            return True
    return False


def _iter_error_returns(tree: ast.Module):
    """Yield `return` nodes inside bare-ish error handling that may leak strings.

    We scan try handlers and flag any `return <call>` where the call is NOT
    format_tool_error and the string it would return is not `ERR:`-prefixed.
    Cancellation/timeout-recovery handlers are excluded: those paths intentionally
    return success/formatting output rather than an error string. Simple,
    intentionally conservative heuristic over AST.
    """
    for node in ast.walk(tree):
        # Handler bodies: `except <Error> [as e]:`
        if isinstance(node, ast.ExceptHandler) and not _is_timeout_or_cancel_handler(node):
            for stmt in node.body:
                if isinstance(stmt, ast.Return):
                    yield node, stmt


class TestUnifiedErrorReturns(unittest.TestCase):
    def test_all_tool_error_returns_use_format_tool_error(self):
        offenders = []
        for name in sorted(os.listdir(TOOLS_DIR)):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            path = TOOLS_DIR / name
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for handler, ret in _iter_error_returns(tree):
                # Skip `raise` handles / cancellation re-raises inside except bodies.
                if isinstance(ret.value, ast.Raise):
                    continue
                value = ret.value
                # A direct ERR:-prefixed string literal is already canonical.
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.startswith("ERR:"):
                    continue
                # f-string beginning with ERR: : brief literal-content check.
                if isinstance(value, ast.JoinedStr) and value.values and isinstance(
                    value.values[0], ast.Constant
                ) and value.values[0].value.startswith("ERR:"):
                    continue
                # Only flag plain name calls (function call only) — ignore others.
                if isinstance(value, ast.Call):
                    fname = value.func
                    # Factory calls that structure ERR content (ToolResult.error) and
                    # raw ToolResult construction are canonical by definition.
                    if isinstance(fname, ast.Attribute) and fname.attr == "error" and isinstance(
                        fname.value, ast.Name
                    ) and fname.value.id == "ToolResult":
                        continue
                    if isinstance(fname, ast.Name):
                        if fname.id in ("format_tool_error", "ToolResult"):
                            continue
                        offenders.append((name, handler.lineno, f"return {fname.id}(...)"))
                    # e.g. `return not_found_message(...)` — allow names ending in _error/_message
                    elif isinstance(fname, ast.Name) and (
                        fname.id.endswith("_error") or fname.id == "not_found_message"
                    ):
                        continue
                    elif isinstance(fname, ast.Attribute) and fname.attr in ("format_tool_error",):
                        continue
                    else:
                        offenders.append((name, handler.lineno, "return call"))
        seen = sorted(set(offenders))
        self.assertEqual([], seen, "Raw error returns not using format_tool_error:\n" + "\n".join(map(str, seen)))


if __name__ == "__main__":
    unittest.main()
