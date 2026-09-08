"""LLM Adapter port interface."""

from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class LLMAdapterPort(Protocol):
    """Port protocol for LLM API wire protocol adapters."""

    def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 32768,
        thinking_effort: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        stream_timeout: Optional[float] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """Streams normalized LLM events from provider wire protocol."""
        ...

    def close(self) -> None:
        """Closes cached clients and releases transport resources."""
        ...
