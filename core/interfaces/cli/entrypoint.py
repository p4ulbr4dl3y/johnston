"""Main CLI entrypoint and argument parser dispatch for Johnston."""
from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from core.infrastructure.platform.logging_setup import setup_logging
from core.infrastructure.platform.paths import CONFIG_DIR


def get_version() -> str:
    """Get application version dynamically from metadata or pyproject.toml."""
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "version") and cli_mod.version is not version:
        try:
            return cli_mod.get_version()
        except Exception:
            pass
    try:
        return version("johnston")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parent.parent.parent.parent / "pyproject.toml"
        if pyproject.exists():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "0.1.0-dev")
            except Exception:
                pass
        return "0.1.0-dev"


def print_models() -> None:
    """Print available providers and models to stdout."""
    from core.provider_manager import ProviderManager

    pm = ProviderManager()
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


def print_mcp() -> None:
    """Print configured MCP servers to stdout."""
    from core.infrastructure.mcp import MCPManager, get_mcp_manager

    mgr = get_mcp_manager()
    servers = mgr.load_servers()
    print("Configured MCP Servers:")
    if not servers:
        print(f"  No MCP servers configured ({CONFIG_DIR}/mcp.json or .johnston/mcp.json)")
        return

    tools_by_server: dict[str, list[str]] = {}
    try:
        active_tools = mgr.get_active_tools()
        for t in active_tools:
            s_name = t.get("_mcp_server")
            t_name = t.get("_mcp_tool_name")
            if s_name and t_name:
                tools_by_server.setdefault(s_name, []).append(t_name)
    except Exception:
        pass

    for idx, s in enumerate(servers):
        enabled = MCPManager.server_enabled(s)
        status = "[enabled]" if enabled else "[disabled]"
        scope = f"[{s.get('scope', 'global')}]"
        name = s.get("name")

        cmd = s.get("command")
        args = s.get("args") or []
        url = s.get("url")
        if cmd:
            cmd_str = f"Command: {cmd}" + (f" {' '.join(str(a) for a in args)}" if args else "")
        elif url:
            cmd_str = f"URL: {url}"
        else:
            cmd_str = "Command: (none)"

        print(f"  * {name} {scope} {status}")
        print(f"    {cmd_str}")

        if not enabled:
            if idx < len(servers) - 1:
                print()
            continue

        tools = tools_by_server.get(name, [])
        if tools:
            print(f"    Tools: {', '.join(tools)}")
        elif url and not cmd:
            print("    Error: HTTP/SSE URL transport not supported yet (only stdio commands supported)")
        else:
            server_status = mgr.get_server_status(name) if hasattr(mgr, "get_server_status") else {}
            err = server_status.get("error") if isinstance(server_status, dict) else None
            if err:
                print(f"    Error: {err}")
            elif not cmd:
                print("    Error: Server configuration missing 'command' or 'url'")
            else:
                print("    Error: No tools reported or server failed to respond")

        if idx < len(servers) - 1:
            print()


def _print_resume_hint(app: Any) -> None:
    """Print command to resume the session if it has active messages."""
    get_hint = getattr(app, "get_resume_hint", None)
    if callable(get_hint):
        try:
            hint = get_hint()
            if isinstance(hint, str) and hint.strip():
                print(f"\nTo resume this session, run:\n  {hint}")
                return
        except Exception:
            pass

    sid = getattr(app, "current_session_id", None)
    sm = getattr(app, "sm", None)
    if sid and sm is not None:
        try:
            sess = sm.get(sid)
            if sess and (getattr(sess, "messages", None) or getattr(sess, "agent_history", None)):
                print(f"\nTo resume this session, run:\n  johnston --resume {sid}")
        except Exception:
            pass


def _dispatch_version() -> str:
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "get_version"):
        return cli_mod.get_version()
    return get_version()


def _dispatch_roles(args: Any = None) -> int:
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "print_roles"):
        cli_mod.print_roles()
        return 0
    from core.interfaces.cli.commands.roles_cmd import run_roles
    return run_roles(args)


def _dispatch_models() -> int:
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "print_models"):
        cli_mod.print_models()
        return 0
    print_models()
    return 0


def _dispatch_skills(args: Any = None) -> int:
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "print_skills"):
        cli_mod.print_skills()
        return 0
    from core.interfaces.cli.commands.skills_cmd import run_skills
    return run_skills(args)


def _dispatch_mcp() -> int:
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "print_mcp"):
        cli_mod.print_mcp()
        return 0
    print_mcp()
    return 0


def _dispatch_rules(args: Any = None) -> int:
    cli_mod = sys.modules.get("cli")
    if cli_mod and hasattr(cli_mod, "print_rules"):
        cli_mod.print_rules()
        return 0
    from core.interfaces.cli.commands.rules_cmd import run_rules
    return run_rules(args)


def build_parser() -> argparse.ArgumentParser:
    """Build root ArgumentParser with subcommands and backward-compatible flags."""
    parser = argparse.ArgumentParser(
        prog="johnston",
        description="Johnston Coding Agent",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        default=None,
        help="Resume specific session ID (or pick from list if ID omitted)",
    )
    parser.add_argument("-v", "--version", action="store_true", help="Show application version")

    # Legacy flags for backward compatibility
    parser.add_argument("--models", action="store_true", help="List available providers and models")
    parser.add_argument("--skills", action="store_true", help="List available skills")
    parser.add_argument("--mcp", action="store_true", help="List configured MCP servers")
    parser.add_argument("--roles", action="store_true", help="List available agent roles (execution modes + subagents)")
    parser.add_argument("--rules", action="store_true", help="List active project instructions and rules")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # config subparser
    config_p = subparsers.add_parser("config", help="Inspect and modify application settings")
    config_subs = config_p.add_subparsers(dest="config_action", help="Config actions")

    config_subs.add_parser("list", help="List all configuration settings")

    get_p = config_subs.add_parser("get", help="Get a configuration setting value")
    get_p.add_argument("key", help="Configuration key (e.g. llm.context_limit, theme)")

    set_p = config_subs.add_parser("set", help="Set a configuration setting value")
    set_p.add_argument("key", help="Configuration key (e.g. llm.context_limit, theme)")
    set_p.add_argument("value", help="Configuration value to set")

    unset_p = config_subs.add_parser("unset", help="Reset a configuration setting to default")
    unset_p.add_argument("key", help="Configuration key (e.g. llm.context_limit, theme)")

    # roles subparser
    subparsers.add_parser("roles", help="List available agent roles (execution modes + subagents)")

    # skills subparser
    subparsers.add_parser("skills", help="List available skills")

    # rules subparser
    subparsers.add_parser("rules", help="List active project instructions and rules")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for Johnston CLI."""
    setup_logging()

    parser = build_parser()
    args = parser.parse_args(argv)

    # Legacy flag dispatching in exact priority order
    if args.version:
        print(f"johnston {_dispatch_version()}")
        sys.exit(0)

    if args.roles:
        _dispatch_roles(args)
        sys.exit(0)

    if args.models:
        _dispatch_models()
        sys.exit(0)

    if args.skills:
        _dispatch_skills(args)
        sys.exit(0)

    if args.mcp:
        _dispatch_mcp()
        sys.exit(0)

    if args.rules:
        _dispatch_rules(args)
        sys.exit(0)

    # Subcommands
    if args.subcommand == "config":
        from core.interfaces.cli.commands.config_cmd import run_config

        code = run_config(args)
        sys.exit(code)
    elif args.subcommand == "roles":
        code = _dispatch_roles(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "skills":
        code = _dispatch_skills(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "rules":
        code = _dispatch_rules(args)
        sys.exit(code if code is not None else 0)

    from app import JohnstonApp

    app = JohnstonApp(
        resume_session_id=args.resume,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        pass

    _print_resume_hint(app)
    sys.exit(0)
