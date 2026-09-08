"""Domain entities for models catalog and pricing."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.domain.defaults.config import DEFAULT_CONTEXT_LIMIT


@dataclass
class ModelPricing:
    """Pricing information per token in USD."""

    prompt: float = 0.0
    completion: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        res: Dict[str, float] = {"prompt": self.prompt, "completion": self.completion}
        if self.cache_read > 0:
            res["cache_read"] = self.cache_read
        if self.cache_write > 0:
            res["cache_write"] = self.cache_write
        return res

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ModelPricing":
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            prompt=float(data.get("prompt") or 0.0),
            completion=float(data.get("completion") or 0.0),
            cache_read=float(data.get("cache_read") or 0.0),
            cache_write=float(data.get("cache_write") or 0.0),
        )


@dataclass
class ModelSpec:
    """Specification of an AI model in the catalog."""

    id: str
    name: str = ""
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    pricing: ModelPricing = field(default_factory=ModelPricing)
    modalities: List[str] = field(default_factory=lambda: ["text"])

    @property
    def has_vision(self) -> bool:
        return "image" in self.modalities or "vision" in self.modalities
