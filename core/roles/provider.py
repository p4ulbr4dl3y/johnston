"""Provider switching for a subagent based on its role definition."""


def rebind_provider(subagent, provider_key: str) -> None:
    """Rebind an existing subagent agent to a different provider in place.

    Builds a fresh agent for the target provider and copies its configuration
    (including the HTTP client bound to that provider's base_url/api_key) onto
    the existing subagent object, preserving caller-attached identity fields.
    Keeps the same object so session.agent and surrounding code stay valid.
    """
    from core.provider_manager import ProviderManager

    pm = ProviderManager()
    rebuilt = pm.create_agent_for_provider(provider_key)
    if rebuilt is None:
        return

    preserved = {
        name: getattr(subagent, name)
        for name in ("app", "is_subagent", "history", "tools", "project_dir", "cwd")
        if hasattr(subagent, name)
    }
    subagent.__dict__.update(rebuilt.__dict__)
    for name, value in preserved.items():
        setattr(subagent, name, value)


def apply_provider(subagent, definition) -> None:
    """If the role pins a provider, switch the subagent to it.

    Otherwise inherit the active provider from the parent (the default). Raises
    ``ValueError`` when the pinned provider is not connected.
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
