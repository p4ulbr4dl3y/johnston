"""Provider switching for a subagent based on its role definition."""

from typing import Any

from core.domain.policies.role_policy import AgentRole

# Provider-bound attributes copied from a freshly built agent onto the live
# subagent during a rebind. Everything else (identity plumbing, history,
# tools, prompt, role, metrics) intentionally stays with the existing object.
_PROVIDER_BOUND_FIELDS = (
    "api_key",
    "model",
    "base_url",
    "provider_key",
    "api_type",
    "headers",
    "extra_body",
    "reasoning_effort",
    "thinking_effort",
    "chunk_timeout",
    "max_tokens",
    "max_retries",
    "retry_delay",
    "retry_backoff",
    "max_retry_delay",
    "client",
    "subagent_schema",
)


def rebind_provider(subagent: Any, provider_key: str) -> None:
    """Rebind an existing subagent agent to a different provider in place.

    Builds a fresh agent for the target provider and copies only its
    provider-bound configuration (including the HTTP client bound to that
    provider's base_url/api_key) onto the existing subagent object. Keeps the
    same object so session.agent and surrounding code stay valid.

    Raises ``ValueError`` when the provider cannot produce an agent.
    """
    from core.provider_manager import ProviderManager

    pm = ProviderManager()
    rebuilt = pm.create_agent_for_provider(provider_key)
    if rebuilt is None:
        raise ValueError(f"provider '{provider_key}' did not produce an agent")

    for field in _PROVIDER_BOUND_FIELDS:
        if hasattr(rebuilt, field):
            setattr(subagent, field, getattr(rebuilt, field))


def apply_provider(subagent: Any, definition: AgentRole) -> None:
    """If the role pins a provider, switch the subagent to it.

    Otherwise inherit the active provider from the parent (the default). Raises
    ``ValueError`` when the pinned provider is not connected or cannot back an
    agent.
    """
    provider = getattr(definition, "provider", None)
    if not provider:
        return
    from core.provider_manager import ProviderManager

    pm = ProviderManager()
    pm.load_providers()
    if not pm.is_provider_connected(provider):
        raise ValueError(f"provider '{provider}' for role '{definition.key}' is not connected")
    if getattr(subagent, "provider_key", "") != provider:
        rebind_provider(subagent, provider)
