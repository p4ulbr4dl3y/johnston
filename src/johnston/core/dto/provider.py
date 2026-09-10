from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class ModelInfoDTO:
    name: str
    display_name: str
    provider: str
    context_window: int = 0
    supports_vision: bool = False
    supports_thinking: bool = False


@dataclass(slots=True, frozen=True)
class ProviderDTO:
    name: str
    is_configured: bool
    models: list[ModelInfoDTO] = field(default_factory=list)
    key: str = ""
    is_active: bool = False
    is_disabled: bool = False
