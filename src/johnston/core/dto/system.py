from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class SkillDTO:
    name: str
    description: str
    path: str
    enabled: bool = True
    is_project: bool = False


@dataclass(slots=True, frozen=True)
class RuleDTO:
    title: str
    path: str
    content_preview: str
    scope: str


@dataclass(slots=True, frozen=True)
class TaskDTO:
    task_id: str
    command: str
    status: str
    returncode: int | None = None
    log_path: str = ""


@dataclass(slots=True, frozen=True)
class GitStateDTO:
    branch: str
    is_dirty: bool
    changed_files: int = 0


@dataclass(slots=True, frozen=True)
class PermissionRequestDTO:
    tool_name: str
    args: dict[str, Any]
    risk_level: str
    reason: str = ""
