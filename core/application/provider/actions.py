"""Pure core utility functions for provider/model/thinking-effort operations.

Each function operates on the ProviderManager and/or agent without any
knowledge of Textual widgets, screens, or UI orchestration.  They exist
so that ``widgets/commands.py`` can remain a thin UI wrapper.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from core.infrastructure.runtime.background import spawn_background_task
from core.provider_manager import ProviderManager, is_local_provider

logger = logging.getLogger(__name__)


# ── API key / provider credentials ──────────────────────────────────────

def _refresh_models_background(pm: ProviderManager) -> None:
    """Fire-and-forget model refresh so the UI is not blocked."""
    if hasattr(pm, "fetch_models_grouped"):
        # Strongly-referenced task: a bare create_task could be GC'd mid-flight.
        spawn_background_task(pm.fetch_models_grouped())


def set_provider_credentials(
    pm: ProviderManager,
    provider_key: str,
    api_key: str,
    app: Any,
) -> bool:
    """Persist a non-empty API key, enable the provider, recreate the agent.

    When *api_key* is non-empty the provider is enabled, activated and its models
    are re-fetched in the background.  For an empty key the provider is only
    activated when it needs no key (local/``requires_key=False``), so an
    accidental enter-without-input cannot silently switch to and enable a
    key-required provider.  Returns ``True`` when models were queued (non-empty
    key), ``False`` otherwise.
    """
    if api_key:
        pm.set_provider_api_key(provider_key, api_key)
        pm.set_provider_disabled(provider_key, False)
        pm.recreate_active_agent(app, provider_key=provider_key)
        _refresh_models_background(pm)
        return True

    # Empty key: only "connect" (activate) providers that need no API key.
    pdef = pm.load_provider_def(provider_key)
    if pdef is None:
        return False
    needs_key = pdef.requires_key is not False and not is_local_provider(
        provider_key, pdef.api_type, pdef.base_url, pdef.requires_key
    )
    if needs_key and not pm.get_api_key(provider_key):
        return False
    if not pdef.enabled:
        pm.set_provider_disabled(provider_key, False)
    if provider_key != pm.get_active_provider_key():
        pm.recreate_active_agent(app, provider_key=provider_key)
    return False



# ── Models ──────────────────────────────────────────────────────────────


async def fetch_grouped_models(
    pm: ProviderManager,
) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """Fetch models grouped by provider.

    Returns
    -------
    (grouped_models, is_disconnected)
        *grouped_models* is the raw result of ``fetch_models_grouped()``.
        *is_disconnected* is ``True`` when no provider is connected at all.
    """
    grouped_models = await pm.fetch_models_grouped()
    if grouped_models:
        return grouped_models, False

    # Check whether *any* provider is connected at all.
    providers = pm.load_providers()
    connected = any(
        pm.is_provider_connected(k, v) for k, v in providers.items()
    )
    return grouped_models, not connected


def select_model(
    pm: ProviderManager,
    agent: Any,
    provider_key: str,
    model_name: str,
    app: Any,
) -> None:
    """Persist the model selection on *agent* and in the provider config.

    When switching to a different active provider the agent is re-created
    for that provider so history/role are preserved before the model is set.
    """
    if provider_key != pm.get_active_provider_key():
        pm.recreate_active_agent(app, provider_key=provider_key)

    if hasattr(agent, "model"):
        agent.model = model_name
    pm.set_provider_model(provider_key, model_name)


# ── Thinking effort ─────────────────────────────────────────────────────


def get_current_thinking_effort(
    pm: ProviderManager,
    agent: Any,
) -> Tuple[str, str, str]:
    """Return ``(provider_key, model_name, current_effort)``.

    Derives the provider/model from the active provider / agent.
    """
    provider_key = pm.get_active_provider_key()
    model_name = getattr(agent, "model", "") or pm.get_provider_model(provider_key)
    current_effort = ""
    if hasattr(pm, "get_provider_thinking_effort"):
        current_effort = pm.get_provider_thinking_effort(provider_key, model_name)
    return provider_key, model_name, current_effort


def set_thinking_effort(
    pm: ProviderManager,
    provider_key: str,
    model_name: str,
    effort: str,
    app: Any,
) -> None:
    """Persist the thinking effort and recreate the agent."""
    if hasattr(pm, "set_provider_thinking_effort"):
        pm.set_provider_thinking_effort(provider_key, model_name, effort)
    pm.recreate_active_agent(app)
