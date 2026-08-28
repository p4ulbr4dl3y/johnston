"""Base class for slash commands."""
from __future__ import annotations


class BaseCommand:
    """Base class for slash commands."""

    name: str = ""
    description: str = ""
    aliases: list[str] = []

    async def execute(self, app) -> None:
        raise NotImplementedError
