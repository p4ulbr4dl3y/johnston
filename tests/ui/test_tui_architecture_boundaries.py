"""Architectural boundary tests for TUI screens.

Enforces strict decoupling of presentation screens from internal Core managers,
ensuring screens interact with JohnstonClient and DTOs instead of direct core singletons.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

SCREENS_DIR = Path(__file__).resolve().parents[2] / "src" / "johnston" / "tui" / "presentation" / "screens"

ALLOWED_CORE_PREFIXES = (
    "johnston.core.client",
    "johnston.core.dto",
)

GLOBAL_FORBIDDEN_NAMES = {
    "catalog",
    "models_catalog",
    "get_skill_manager",
    "SkillManager",
    "GitWorktreeManager",
    "git_worktree",
    "interactor",
    "list_subagent_sessions",
}

FILE_SPECIFIC_FORBIDDEN: dict[str, set[str]] = {
    "skills.py": {"CONFIG_DIR", "get_skill_manager", "SkillManager"},
    "mcp.py": {"CONFIG_DIR"},
    "providers.py": {"CONFIG_DIR", "cached_json_read", "catalog", "models_catalog"},
    "workspace.py": {"interactor", "PermissionManager"},
    "branch.py": {"GitWorktreeManager", "git_worktree"},
    "tasks.py": {"list_subagent_sessions"},
}


class ImportVisitor(ast.NodeVisitor):
    """AST visitor collecting all imported module names, aliases, and imported symbols."""

    def __init__(self) -> None:
        self.imports: list[tuple[int, str, str]] = []  # (lineno, module_or_name, asname)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append((node.lineno, alias.name, alias.asname or alias.name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            full_name = f"{module}.{alias.name}" if module else alias.name
            self.imports.append((node.lineno, full_name, alias.asname or alias.name))
        self.generic_visit(node)


class TestTuiArchitectureBoundaries(unittest.TestCase):
    """Verify architectural boundaries across all TUI screens via AST inspection."""

    def test_screens_directory_exists(self) -> None:
        self.assertTrue(SCREENS_DIR.is_dir(), f"Screens directory not found: {SCREENS_DIR}")

    def test_no_forbidden_imports_in_screens(self) -> None:
        """Verify ALL .py files in screens forbid any internal core modules (only client/dto allowed)."""
        screen_files = sorted(SCREENS_DIR.glob("*.py"))
        self.assertGreater(len(screen_files), 20, "Expected all screen modules to be present")

        violations: list[str] = []

        for screen_path in screen_files:
            file_name = screen_path.name
            source = screen_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(screen_path))

            visitor = ImportVisitor()
            visitor.visit(tree)

            specific_forbidden = FILE_SPECIFIC_FORBIDDEN.get(file_name, set())

            for lineno, import_target, asname in visitor.imports:
                parts = import_target.split(".")
                imported_symbols = set(parts) | {asname}

                # Strictly forbid any internal core imports: only johnston.core.client and johnston.core.dto allowed
                if import_target == "johnston.core" or import_target.startswith("johnston.core."):
                    if not any(import_target.startswith(prefix) for prefix in ALLOWED_CORE_PREFIXES):
                        violations.append(
                            f"{file_name}:{lineno} forbidden internal core import '{import_target}' "
                            f"(only johnston.core.client and johnston.core.dto are allowed)"
                        )

                # Check globally forbidden symbols
                for forbidden in GLOBAL_FORBIDDEN_NAMES:
                    if forbidden in imported_symbols:
                        violations.append(
                            f"{file_name}:{lineno} forbidden global import '{forbidden}' in '{import_target}'"
                        )

                # Check file-specific forbidden symbols
                for forbidden in specific_forbidden:
                    if forbidden in imported_symbols:
                        violations.append(
                            f"{file_name}:{lineno} forbidden screen-specific import '{forbidden}' in '{import_target}'"
                        )

        if violations:
            msg = "Architecture boundary violations found in TUI screens:\n" + "\n".join(violations)
            self.fail(msg)

    def test_footer_widgets_no_catalog_import(self) -> None:
        """Verify status_footer.py and subagent_footer.py do not directly import models_catalog.catalog."""
        widgets_dir = SCREENS_DIR.parent / "widgets"
        for widget_name in ("status_footer.py", "subagent_footer.py"):
            widget_path = widgets_dir / widget_name
            self.assertTrue(widget_path.exists(), f"Widget file missing: {widget_name}")
            source = widget_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(widget_path))
            visitor = ImportVisitor()
            visitor.visit(tree)
            for lineno, import_target, asname in visitor.imports:
                self.assertNotIn(
                    "models_catalog.catalog",
                    import_target,
                    f"{widget_name}:{lineno} forbidden models_catalog.catalog import in '{import_target}'",
                )
                if asname == "catalog" or import_target.endswith(".catalog"):
                    self.fail(f"{widget_name}:{lineno} direct catalog import '{import_target}'")

    def test_all_screens_use_client_or_dtos(self) -> None:
        """Sanity check that key screens rely on JohnstonClient facade or core DTOs."""
        client_screens = [
            "skills.py",
            "providers.py",
            "mcp.py",
            "workspace.py",
            "tasks.py",
            "branch.py",
        ]

        for screen_name in client_screens:
            file_path = SCREENS_DIR / screen_name
            self.assertTrue(file_path.exists(), f"Screen file missing: {screen_name}")
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))

            visitor = ImportVisitor()
            visitor.visit(tree)

            client_imports = [
                target for _, target, _ in visitor.imports if "JohnstonClient" in target or "client" in target
            ]
            self.assertTrue(
                len(client_imports) > 0,
                f"{screen_name} does not reference JohnstonClient or client facade",
            )

        # model.py is a pure dumb selection screen relying on ModelInfoDTO
        model_file = SCREENS_DIR / "model.py"
        source = model_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(model_file))
        visitor = ImportVisitor()
        visitor.visit(tree)
        dto_imports = [target for _, target, _ in visitor.imports if "DTO" in target or "dto" in target]
        self.assertTrue(len(dto_imports) > 0, "model.py does not import DTOs")


if __name__ == "__main__":
    unittest.main()
