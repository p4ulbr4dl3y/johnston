"""CLI entry module for Johnston (re-exporting from johnston_cli)."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Sequence

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from johnston_cli.entrypoint import main_j, main_johnston
from johnston_core.interfaces.cli.commands.mcp_cmd import print_mcp
from johnston_core.interfaces.cli.commands.provider_cmd import print_models
from johnston_core.interfaces.cli.commands.roles_cmd import print_roles
from johnston_core.interfaces.cli.commands.rules_cmd import print_rules
from johnston_core.interfaces.cli.commands.skills_cmd import print_skills
from johnston_core.interfaces.cli.entrypoint import (
    build_parser,
)
from johnston_core.interfaces.cli.entrypoint import (
    main as _entrypoint_main,
)

__all__ = [
    "build_parser",
    "get_version",
    "main",
    "main_j",
    "main_johnston",
    "print_mcp",
    "print_models",
    "print_roles",
    "print_rules",
    "print_skills",
    "tomllib",
    "version",
]


def get_version() -> str:
    """Get application version dynamically from metadata or pyproject.toml."""
    try:
        return version("johnston")
    except PackageNotFoundError:
        pyproject = Path(__file__).parent / "pyproject.toml"
        if pyproject.exists():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "0.1.0-dev")
            except Exception:
                pass
        return "0.1.0-dev"


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry delegating to core entrypoint."""
    return _entrypoint_main(argv)


if __name__ == "__main__":
    main()
