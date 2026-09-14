"""CLI serve command: run the Johnston JSON-RPC daemon over stdio."""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from johnston.core.application.provider.provider_manager import ProviderManager
from johnston.core.client import JohnstonClient
from johnston.core.domain.policies.role_policy import AgentMode

logger = logging.getLogger(__name__)


def _load_agent_config(pm: Any) -> dict[str, Any]:
    """Resolve defaults for the client from provider configuration.

    Returns kwargs contribution to JohnstonClient only when a provider is
    actually configured, so the daemon information/state methods stay
    functional on machines without provider setup.
    """
    try:
        provider_key = pm.get_active_provider_key()
        if not provider_key:
            return {}
        return {"provider": provider_key}
    except Exception:
        logger.debug("Failed to resolve provider config", exc_info=True)
        return {}


def _build_client(args: Any, pm: Any) -> JohnstonClient:
    """Construct the JohnstonClient backing the daemon from CLI args."""
    role = getattr(args, "role", None) or "worker"
    model = getattr(args, "model", None) or None

    effort_arg = getattr(args, "effort", None)
    effort = effort_arg.strip().lower() if isinstance(effort_arg, str) and effort_arg.strip() else None

    if getattr(args, "sandbox", False) is True:
        sandbox: bool | None = True
    elif getattr(args, "no_sandbox", False) is True:
        sandbox = False
    else:
        from johnston.core.infrastructure.config.config_helpers import load_sandbox_config

        sandbox = load_sandbox_config()

    mode = getattr(args, "mode", None) or AgentMode.HEADLESS

    kwargs: dict[str, Any] = {
        "provider": getattr(args, "provider", None),
        "model": model,
        "role": role,
        "mode": mode,
        "effort": effort,
        "sandbox": sandbox,
        "pm": pm,
    }
    if "provider" in kwargs and not kwargs["provider"]:
        del kwargs["provider"]
        kwargs.update(_load_agent_config(pm))

    client = JohnstonClient(**kwargs)
    if client.agent is not None:
        from johnston.core.application.roles.apply import apply_role

        apply_role(client.agent, role, mode=AgentMode.HEADLESS)
        if model and hasattr(client.agent, "model"):
            client.agent.model = model
        if effort and hasattr(client.agent, "thinking_effort"):
            client.agent.thinking_effort = effort
            if hasattr(client.agent, "reasoning_effort"):
                client.agent.reasoning_effort = effort
    return client


def _apply_workspace_roots(args: Any, pm: Any) -> None:
    """Register workspace roots without mutating global permission state."""
    ws = getattr(args, "workspace", None) or []
    if not ws:
        return
    from johnston.core.application.permission.interactor import add_workspace_root

    for w in ws:
        if w:
            try:
                add_workspace_root(w, scope="session")
            except Exception:
                logger.debug("Failed to add workspace root: %s", w, exc_info=True)


async def run_serve(args: Any, pm: Any | None = None) -> int:
    """Run the JSON-RPC daemon over stdio until stdin reaches EOF.

    Spawns a JohnstonClient (a fresh instance per invocation) and serves the
    daemon RPC protocol on stdin/stdout. stdout carries protocol messages
    only; all logging goes to stderr/files.
    """
    from johnston.core.rpc.server import _serve

    close_pm = False
    if pm is None:
        pm = ProviderManager()
        close_pm = True

    try:
        _apply_workspace_roots(args, pm)
        client = _build_client(args, pm)
        return await _serve(client, stdin=sys.stdin, stdout=sys.stdout)
    finally:
        if close_pm:
            try:
                await asyncio.shield(pm.close())
            except BaseException:
                pass


def run_serve_entry(args: Any) -> int:
    """Synchronous entrypoint for the ``serve`` subcommand."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(run_serve(args))).result()
    return asyncio.run(run_serve(args))
