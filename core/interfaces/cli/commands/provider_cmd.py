"""CLI commands for managing LLM providers and models."""
from __future__ import annotations

import sys
from typing import Any, Optional

from core.interfaces.cli.formatter import format_table

if False:  # type checking only
    from core.application.provider.provider_manager import ProviderManager


def _get_pm(pm: Optional[ProviderManager] = None) -> ProviderManager:
    if pm is not None:
        return pm
    from core.application.provider.provider_manager import ProviderManager

    return ProviderManager()


def list_providers(pm: Optional[ProviderManager] = None, as_json: bool = False) -> int:
    """Format and print table or JSON with configured providers and their states."""
    import json

    pm = _get_pm(pm)

    providers = pm.load_providers(include_disabled=True)
    active_key = pm.get_active_provider_key()
    disabled_keys = set(pm.get_disabled_providers())

    headers = ["Active", "Provider", "Model", "API Key status", "State"]
    rows: list[list[str]] = []

    for key, info in providers.items():
        is_active = key == active_key
        active_mark = "*" if is_active else ""

        model = pm.get_provider_model(key)
        if not model:
            models = info.get("models") or []
            model = models[0] if models else "-"

        api_key = pm.get_api_key(key) or info.get("api_key", "")
        p_def = pm.load_provider_def(key)
        needs_key = pm.provider_needs_key(key, p_def) if p_def else True
        if not needs_key:
            key_status = "not required"
        elif api_key:
            key_status = "set"
        else:
            key_status = "unset"

        is_disabled = (key in disabled_keys) or not info.get("enabled", True)
        if is_disabled:
            state = "disabled"
        elif is_active:
            state = "active"
        else:
            state = "ready"

        rows.append([active_mark, key, model, key_status, state])

    if as_json:
        data = [
            {
                "active": row[0] == "*",
                "provider": row[1],
                "model": row[2],
                "key_status": row[3],
                "state": row[4],
            }
            for row in rows
        ]
        print(json.dumps(data, indent=2))
        return 0

    print(format_table(headers, rows))
    return 0


def set_key(name: str, key: Optional[str] = None, pm: Optional[ProviderManager] = None) -> int:
    """Save provider API key."""
    if not name:
        print("Error: Provider name is required.", file=sys.stderr)
        return 1

    if key is None:
        if sys.stdin.isatty():
            import getpass

            key = getpass.getpass(f"Enter API key for '{name}': ")
        else:
            key = sys.stdin.read().strip()
    elif key == "-":
        key = sys.stdin.read().strip()

    if not key:
        print("Error: Provider name and API key are required.", file=sys.stderr)
        return 1
    pm = _get_pm(pm)
    pm.set_provider_api_key(name, key)
    print(f"API key for '{name}' saved.")
    return 0


def set_model(name: str, model: str, pm: Optional[ProviderManager] = None) -> int:
    """Save active model for provider."""
    if not name or not model:
        print("Error: Provider name and model are required.", file=sys.stderr)
        return 1
    pm = _get_pm(pm)
    pm.set_provider_model(name, model)
    print(f"Model for '{name}' set to '{model}'.")
    return 0


def enable_provider(name: str, pm: Optional[ProviderManager] = None) -> int:
    """Enable a provider."""
    if not name:
        print("Error: Provider name is required.", file=sys.stderr)
        return 1
    pm = _get_pm(pm)
    all_providers = pm.load_providers(include_disabled=True)
    if name not in all_providers:
        print(f"Error: Provider '{name}' not found.", file=sys.stderr)
        return 1
    pm.set_provider_disabled(name, False)
    print(f"Provider '{name}' enabled.")
    return 0


def disable_provider(name: str, pm: Optional[ProviderManager] = None) -> int:
    """Disable a provider."""
    if not name:
        print("Error: Provider name is required.", file=sys.stderr)
        return 1
    pm = _get_pm(pm)
    all_providers = pm.load_providers(include_disabled=True)
    if name not in all_providers:
        print(f"Error: Provider '{name}' not found.", file=sys.stderr)
        return 1
    pm.set_provider_disabled(name, True)
    print(f"Provider '{name}' disabled.")
    return 0


def add_provider_cmd(
    name: str,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    pm: Optional[ProviderManager] = None,
) -> int:
    """Add new provider definition."""
    if not name or not model:
        print("Error: Provider name and model are required.", file=sys.stderr)
        return 1
    pm = _get_pm(pm)
    pm.add_provider(name, model=model, api_key=api_key, base_url=base_url)
    print(f"Provider '{name}' added.")
    return 0


def rm_provider_cmd(name: str, pm: Optional[ProviderManager] = None) -> int:
    """Remove provider definition."""
    if not name:
        print("Error: Provider name is required.", file=sys.stderr)
        return 1
    pm = _get_pm(pm)
    existed = pm.remove_provider(name)
    if not existed:
        print(f"Error: Provider '{name}' not found.", file=sys.stderr)
        return 1
    print(f"Provider '{name}' removed.")
    return 0


def run_provider(args: Any = None, pm: Optional[ProviderManager] = None) -> int:
    """Execute provider subcommand based on parsed arguments."""
    action = getattr(args, "provider_action", None) if args is not None else None

    if action is None or action == "list":
        return list_providers(pm, as_json=bool(getattr(args, "json", False)))
    if action == "set-key":
        return set_key(getattr(args, "name", ""), getattr(args, "key", None), pm)
    if action == "set-model":
        return set_model(getattr(args, "name", ""), getattr(args, "model", ""), pm)
    if action == "enable":
        return enable_provider(getattr(args, "name", ""), pm)
    if action == "disable":
        return disable_provider(getattr(args, "name", ""), pm)
    if action == "add":
        return add_provider_cmd(
            getattr(args, "name", ""),
            getattr(args, "model", ""),
            api_key=getattr(args, "api_key", None),
            base_url=getattr(args, "base_url", None),
            pm=pm,
        )
    if action == "rm":
        return rm_provider_cmd(getattr(args, "name", ""), pm)

    print(f"Error: Unknown provider action '{action}'", file=sys.stderr)
    return 1


def print_models() -> None:
    """Print available providers and models to stdout (legacy format)."""
    pm = _get_pm()
    providers = pm.load_providers()
    active_key = pm.get_active_provider_key()
    print("Available Johnston Providers & Models:")
    items = []
    for key, info in providers.items():
        api_key = pm.get_api_key(key) or info.get("api_key", "")
        models = info.get("models") or ([info["model"]] if info.get("model") else [])
        if not api_key and not models:
            continue
        items.append((key, info, api_key, models))

    for idx, (key, info, api_key, models) in enumerate(items):
        is_active = "*" if key == active_key else " "
        name = info.get("name") or key
        model = info.get("model") or (models[0] if models else "not configured")
        key_status = "[key set]" if api_key else "[no key]"
        base_url = info.get("base_url") or ""

        print(f"{is_active} [{key}] {name} {key_status}")
        if model and model != "not configured":
            print(f"    Active Model: {model}")
        if models:
            print(f"    Models: {', '.join(models[:5])}{' ...' if len(models) > 5 else ''}")
        if base_url:
            print(f"    Base URL: {base_url}")
        if idx < len(items) - 1:
            print()
