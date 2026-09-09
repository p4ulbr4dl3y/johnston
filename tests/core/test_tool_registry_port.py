"""Regression tests for ToolRegistryPort and automatic agent tool initialization."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import johnston.core.domain.ports.tool_registry as tr_port
from johnston.core.application.provider.provider_manager import ProviderManager
from johnston.core.domain.ports.tool_registry import (
    ToolRegistryPort,
    get_default_tool_registry,
    register_tool_registry_factory,
    set_default_tool_registry,
)


@pytest.fixture(autouse=True)
def restore_tool_registry():
    """Ensure tool registry global state is restored after tests."""
    original_reg = tr_port._default_tool_registry
    original_factory = tr_port._tool_registry_factory
    yield
    tr_port.set_default_tool_registry(original_reg)
    tr_port.register_tool_registry_factory(original_factory)


def test_get_default_tool_registry_none_when_unset():
    """Test get_default_tool_registry returns None when unset without port-level imports."""
    tr_port._default_tool_registry = None
    tr_port._tool_registry_factory = None
    assert get_default_tool_registry() is None


def test_get_default_tool_registry_factory_resolution():
    """Test get_default_tool_registry resolves from factory if registry is None."""
    tr_port._default_tool_registry = None
    mock_registry = MagicMock(spec=ToolRegistryPort)
    register_tool_registry_factory(lambda: mock_registry)
    assert get_default_tool_registry() is mock_registry


def test_provider_manager_create_agent_tools_initialization():
    """Test ProviderManager creates agent with non-empty tools and valid executors."""
    pm = ProviderManager()
    agent = pm.create_agent_for_provider("openai")
    assert agent is not None
    assert isinstance(agent.tools, list)
    assert len(agent.tools) > 0
    assert callable(agent.tool_executor)
    assert callable(agent.default_tools_provider)
    assert agent.tools == agent.default_tools_provider()


def test_provider_manager_create_agent_with_custom_tool_registry():
    """Test ProviderManager respects custom tool registry passed into create_agent_for_provider."""
    mock_registry = MagicMock(spec=ToolRegistryPort)
    custom_tools = [{"type": "function", "function": {"name": "custom_dummy_tool"}}]
    mock_registry.get_default_tools.return_value = custom_tools
    mock_registry.execute_tool = AsyncMock()
    mock_registry.process_image_file = MagicMock()
    mock_registry.get_subagent_schema.return_value = {"name": "invoke_subagent"}

    pm = ProviderManager()
    agent = pm.create_agent_for_provider("openai", tool_registry=mock_registry)
    assert agent is not None
    assert agent.tools == custom_tools
    assert agent.tool_executor == mock_registry.execute_tool
    assert agent.default_tools_provider == mock_registry.get_default_tools
    assert agent.subagent_schema == {"name": "invoke_subagent"}


def test_set_default_tool_registry_override():
    """Test setting and overriding default tool registry."""
    mock_registry = MagicMock(spec=ToolRegistryPort)
    set_default_tool_registry(mock_registry)
    assert get_default_tool_registry() is mock_registry
