from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple


class BaseApiAdapter:
    """Base API Adapter interface for LLM formats.

    Adapters yield normalized events so the agent loop can consume them
    uniformly regardless of provider wire protocol:
      - ("adapter_text", str)        : a text delta to append to the reply
      - ("adapter_tool_call", dict)  : {"id", "name", "arguments"(JSON str)}
      - ("adapter_usage", dict)      : {"prompt_tokens", "completion_tokens",
                                        "total_tokens", "cache_read_tokens"}
    """

    async def stream_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 4096,
        thinking_effort: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        raise NotImplementedError


def sort_keys_recursive(obj: Any) -> Any:
    """Recursively sorts dictionary keys to guarantee deterministic JSON serialization (stableStringify)."""
    if isinstance(obj, dict):
        return {k: sort_keys_recursive(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [sort_keys_recursive(elem) for elem in obj]
    return obj
