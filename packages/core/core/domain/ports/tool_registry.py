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

    def reset_circuit_breakers(self, session_id: Optional[str] = None) -> None:
        """Reset polling circuit breakers across instantiated tools."""
        ...


_default_tool_registry: Optional[ToolRegistryPort] = None


def set_default_tool_registry(registry: Optional[ToolRegistryPort]) -> None:
    """Sets or overrides the default tool registry port implementation."""
    global _default_tool_registry
    _default_tool_registry = registry


def get_default_tool_registry() -> Optional[ToolRegistryPort]:
    """Resolves the active tool registry port implementation."""
    global _default_tool_registry
    if _default_tool_registry is None:
        try:
            import importlib

            mod = importlib.import_module("tools.registry")
            if _default_tool_registry is None and hasattr(mod, "DefaultToolRegistry"):
                _default_tool_registry = mod.DefaultToolRegistry()
        except Exception:
            pass
    return _default_tool_registry


def reset_tool_circuit_breakers(session_id: Optional[str] = None) -> None:
    """Reset tool circuit breakers on default registry if available."""
    reg = get_default_tool_registry()
    if reg is not None and hasattr(reg, "reset_circuit_breakers"):
        try:
            reg.reset_circuit_breakers(session_id)
        except Exception:
            pass
