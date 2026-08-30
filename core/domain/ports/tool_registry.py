"""Tool registry port defining the boundary between core/provider_manager and tools subsystem."""

from typing import Any, Awaitable, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ToolRegistryPort(Protocol):
    """Port defining the tool registry interface required by LLM providers/agents."""

    def execute_tool(
        self, name: str, args: Optional[Dict[str, Any]] = None, app: Any = None, context: Any = None
    ) -> Awaitable[Any]:
        """Execute a named tool asynchronously."""
        ...

    def get_default_tools(self) -> List[Dict[str, Any]]:
        """Return list of default tool schemas for agent use."""
        ...

    def process_image_file(self, path: str) -> Any:
        """Process an image file synchronously for multimodal payload."""
        ...

    def get_subagent_schema(self) -> Optional[Dict[str, Any]]:
        """Return the schema for invoke_subagent tool."""
        ...

    def is_tool_concurrency_safe(self, name: str, args: Optional[Dict[str, Any]] = None) -> bool:
        """Check if a tool call is safe to run concurrently with other safe tools."""
        ...


_default_tool_registry: Optional[ToolRegistryPort] = None


def set_default_tool_registry(registry: Optional[ToolRegistryPort]) -> None:
    """Sets or overrides the default tool registry port implementation."""
    global _default_tool_registry
    _default_tool_registry = registry


def get_default_tool_registry() -> Optional[ToolRegistryPort]:
    """Resolves the active tool registry port implementation."""
    return _default_tool_registry
