"""Regression tests for domain layer refactoring."""
import pytest

from johnston.core.domain.defaults.errors import (
    StreamStep as DefaultStreamStep,
)
from johnston.core.domain.defaults.errors import (
    ToolResult as DefaultToolResult,
)
from johnston.core.domain.defaults.errors import (
    ToolResultEvent as DefaultToolResultEvent,
)
from johnston.core.domain.defaults.errors import (
    ToolResultStatus as DefaultToolResultStatus,
)
from johnston.core.domain.defaults.errors import (
    normalize_tool_result as default_normalize_tool_result,
)
from johnston.core.domain.entities.provider import (
    _WARNED_BASE_URL_TOKENS,
    reset_warned_base_url_tokens,
    resolve_base_url_placeholders,
)
from johnston.core.domain.entities.role import (
    AgentRole,
    RoleScope,
    normalize_role_scope,
)
from johnston.core.domain.entities.tool_result import (
    StreamStep,
    ToolResult,
    ToolResultEvent,
    ToolResultStatus,
    normalize_tool_result,
)
from johnston.core.domain.policies.role_policy import (
    AgentRole as PolicyAgentRole,
)
from johnston.core.domain.policies.role_policy import (
    RoleScope as PolicyRoleScope,
)
from johnston.core.domain.policies.role_policy import (
    normalize_role_scope as policy_normalize_role_scope,
)
from johnston.core.domain.ports.tool_registry import (
    get_default_tool_registry,
    register_tool_registry_factory,
    set_default_tool_registry,
)


def test_role_entity_and_policy_reexport():
    """Verify AgentRole, RoleScope, normalize_role_scope are identical between entity and policy."""
    assert AgentRole is PolicyAgentRole
    assert RoleScope is PolicyRoleScope
    assert normalize_role_scope is policy_normalize_role_scope

    role = AgentRole(key="test", model="openai/gpt-4o", scope="both")
    assert role.provider == "openai"
    assert role.model == "gpt-4o"
    assert role.scope == "any"


def test_tool_result_entity_and_errors_reexport():
    """Verify tool result entities are identical between entity and defaults.errors."""
    assert ToolResult is DefaultToolResult
    assert ToolResultStatus is DefaultToolResultStatus
    assert ToolResultEvent is DefaultToolResultEvent
    assert StreamStep is DefaultStreamStep
    assert normalize_tool_result is default_normalize_tool_result


@pytest.mark.asyncio
async def test_normalize_tool_result_async():
    """Test normalize_tool_result entity logic."""
    r = await normalize_tool_result("success")
    assert r.status == ToolResultStatus.DONE
    assert r.content == "success"

    r_none = await normalize_tool_result(None)
    assert r_none.content == ""


def test_provider_placeholder_encapsulation():
    """Test placeholder warning deduplication without sys.modules hack."""
    reset_warned_base_url_tokens()
    assert len(_WARNED_BASE_URL_TOKENS) == 0

    res = resolve_base_url_placeholders("https://{mytoken}.com", "custom_p", {})
    assert res == "https://{mytoken}.com"
    assert ("custom_p", "mytoken") in _WARNED_BASE_URL_TOKENS

    # Test custom target_set
    custom_set = set()
    res2 = resolve_base_url_placeholders("https://{other}.com", "p2", {}, warned_tokens=custom_set)
    assert res2 == "https://{other}.com"
    assert ("p2", "other") in custom_set
    assert ("p2", "other") not in _WARNED_BASE_URL_TOKENS

    reset_warned_base_url_tokens()
    assert len(_WARNED_BASE_URL_TOKENS) == 0


def test_port_tool_registry_no_hardcoded_import():
    """Ensure get_default_tool_registry does not import DefaultToolRegistry internally when unset."""
    set_default_tool_registry(None)
    register_tool_registry_factory(None)

    assert get_default_tool_registry() is None
