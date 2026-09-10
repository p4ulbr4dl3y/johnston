from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CompactionResultDTO:
    success: bool
    tokens_before: int = 0
    tokens_after: int = 0
    summary: str = ""
    error: str | None = None


@dataclass(slots=True, frozen=True)
class CommandResultDTO:
    name: str
    success: bool
    message: str = ""
