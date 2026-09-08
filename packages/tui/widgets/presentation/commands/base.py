"""Base class for slash commands."""
from __future__ import annotations


class BaseCommand:
    """Base class for slash commands."""

    name: str = ""
    description: str = ""
    aliases: list[str] = []

    def __init__(self) -> None:
        self.args: list[str] = []

    def set_args(self, args: list[str]) -> None:
        self.args = list(args)

    async def execute(self, app) -> None:
        raise NotImplementedError
