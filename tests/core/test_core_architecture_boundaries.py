from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PACKAGES = ("textual", "johnston.tui")


def is_forbidden_module(mod_name: str) -> bool:
    """Return True if mod_name matches or is a submodule of any forbidden package."""
    return any(mod_name == pkg or mod_name.startswith(f"{pkg}.") for pkg in FORBIDDEN_PACKAGES)


def find_import_violations(py_file: Path, src_dir: Path) -> list[str]:
    """Parse a python file AST and return list of forbidden import violations."""
    violations: list[str] = []
    content = py_file.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(py_file))

    try:
        rel_to_src = py_file.resolve().relative_to(src_dir.resolve())
        pkg_parts = rel_to_src.parent.parts
    except ValueError:
        pkg_parts = ()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if is_forbidden_module(alias.name):
                    violations.append(
                        f"{py_file}:{node.lineno} -> forbidden import: 'import {alias.name}'"
                    )
        elif isinstance(node, ast.ImportFrom):
            raw_module = node.module or ""
            if node.level == 0:
                if is_forbidden_module(raw_module):
                    violations.append(
                        f"{py_file}:{node.lineno} -> forbidden import: 'from {raw_module} import ...'"
                    )
            else:
                # Relative import resolution
                if node.level <= len(pkg_parts):
                    base_parts = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                else:
                    base_parts = ()
                resolved_pkg = ".".join(base_parts)
                resolved_mod = f"{resolved_pkg}.{raw_module}" if raw_module else resolved_pkg

                if is_forbidden_module(resolved_mod):
                    violations.append(
                        f"{py_file}:{node.lineno} -> forbidden relative import: "
                        f"'from {'.' * node.level}{raw_module} import ...' (resolves to '{resolved_mod}')"
                    )
                else:
                    for alias in node.names:
                        full_name = f"{resolved_mod}.{alias.name}" if resolved_mod else alias.name
                        if is_forbidden_module(full_name):
                            violations.append(
                                f"{py_file}:{node.lineno} -> forbidden relative import: "
                                f"'from {'.' * node.level}{raw_module} import {alias.name}' "
                                f"(resolves to '{full_name}')"
                            )

    return violations


def test_core_isolation_boundaries():
    """Verify src/johnston/core has zero imports of textual or johnston.tui."""
    repo_root = Path(__file__).resolve().parents[2]
    src_dir = repo_root / "src"
    core_dir = src_dir / "johnston" / "core"

    assert core_dir.is_dir(), f"Core directory does not exist: {core_dir}"

    py_files = sorted(core_dir.rglob("*.py"))
    assert len(py_files) > 0, f"No Python files found under {core_dir}"

    all_violations: list[str] = []
    for py_file in py_files:
        violations = find_import_violations(py_file, src_dir)
        all_violations.extend(violations)

    error_msg = (
        f"Core isolation boundary violation! Found {len(all_violations)} forbidden import(s) in {core_dir}:\n"
        + "\n".join(f"  - {v}" for v in all_violations)
    )
    assert not all_violations, error_msg


def test_is_forbidden_module():
    """Verify is_forbidden_module matches package and submodules without false positives."""
    assert is_forbidden_module("textual")
    assert is_forbidden_module("textual.app")
    assert is_forbidden_module("textual.widgets.button")
    assert is_forbidden_module("johnston.tui")
    assert is_forbidden_module("johnston.tui.app")
    assert not is_forbidden_module("johnston.core")
    assert not is_forbidden_module("johnston.core.client")
    assert not is_forbidden_module("textual_custom")
    assert not is_forbidden_module("johnston.tui_extra")


def test_find_import_violations_detects_patterns(tmp_path: Path):
    """Verify forbidden import patterns (direct, submodule, relative) are detected."""
    src_dir = tmp_path / "src"
    core_pkg = src_dir / "johnston" / "core"
    core_pkg.mkdir(parents=True)
    sample_file = core_pkg / "sample.py"
    sample_file.write_text(
        """import textual
import textual.widgets
from textual.app import App
import johnston.tui
from johnston.tui import app
from ..tui import widgets
from .. import tui
import os
from johnston.core import client
""",
        encoding="utf-8",
    )

    violations = find_import_violations(sample_file, src_dir)
    assert len(violations) == 7
    violation_text = "\n".join(violations)
    assert "import textual" in violation_text
    assert "import textual.widgets" in violation_text
    assert "from textual.app" in violation_text
    assert "import johnston.tui" in violation_text
    assert "from johnston.tui import" in violation_text
    assert "from ..tui import" in violation_text
    assert "from .. import tui" in violation_text
