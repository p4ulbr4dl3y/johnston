"""Domain entities for rules."""
from dataclasses import dataclass


@dataclass
class RuleDefinition:
    """Domain entity representing a parsed agent instruction rule."""

    name: str
    content: str
    source: str = "global"
