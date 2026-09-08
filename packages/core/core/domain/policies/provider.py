"""Provider/model string helpers (pure domain, no IO)."""
from typing import Optional, Tuple


def split_provider_model(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split a ``provider/model`` string into ``(provider, model)``.

    ``raw`` may be ``None``/empty (returns ``(None, None)``), a bare ``provider``
    key (returns ``(provider, None)``), or ``provider/model`` (returns both parts).
    The provider is lowercased; the model keeps its original case.  Both parts
    are stripped of surrounding whitespace.
    """
    if not raw or not isinstance(raw, str) or not raw.strip():
        return None, None
    raw = raw.strip()
    if "/" in raw:
        provider, model = raw.split("/", 1)
        return provider.strip().lower(), model.strip()
    return raw.lower(), None
