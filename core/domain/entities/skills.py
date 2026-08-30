"""Domain entities for skills."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class SkillScope(Enum):
    """Domain scope of a discovered skill."""

    GLOBAL = "global"
    PROJECT = "project"


@dataclass
class Skill:
    """Structured representation of a discovered skill."""

    name: str
    description: str
    location: str
    content: str
    scope: SkillScope
    hidden: bool

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the dict shape emitted for UI/JSON consumers."""
        return {
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "content": self.content,
            "scope": self.scope.value if isinstance(self.scope, SkillScope) else str(self.scope),
            "hidden": self.hidden,
        }
