import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from core.infrastructure.platform.paths import CONFIG_DIR


def get_version() -> str:
    """Get application version dynamically from metadata or pyproject.toml"""
    try:
        return version("johnston")
    except PackageNotFoundError:
        pyproject = Path(__file__).parent / "pyproject.toml"
        if pyproject.exists():
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "0.1.0-dev")
            except Exception:
                pass
        return "0.1.0-dev"


def print_models():
    """Print available providers and models to stdout"""
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


def print_skills():
    """Print available skills to stdout"""
    from core.application.skills.manager import SkillManager

    skills = SkillManager().list_skills()
    print("Available Johnston Skills:")
    if not skills:
        print(f"  No skills found ({CONFIG_DIR}/skills/ or .johnston/skills/)")
        return
    for s in skills:
        scope = f"[{s.scope.value}]"
        hidden = " [hidden]" if s.hidden else ""
        print(f"  * {s.name} {scope}{hidden}")


def print_mcp():
    """Print configured MCP servers to stdout"""
    from core.infrastructure.mcp import MCPManager, get_mcp_manager

    mgr = get_mcp_manager()
    servers = mgr.load_servers()
    print("Configured MCP Servers:")
    if not servers:
        print(f"  No MCP servers configured ({CONFIG_DIR}/mcp.json or .johnston/mcp.json)")
        return

    tools_by_server = {}
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
            client = mgr.clients.get(name)
            err = getattr(client, "last_error", None) if client else None
            if err:
                print(f"    Error: {err}")
            elif not cmd:
                print("    Error: Server configuration missing 'command' or 'url'")
            else:
                print("    Error: No tools reported or server failed to respond")

        if idx < len(servers) - 1:
            print()


def print_rules():
    """Print active project instructions and rules summary to stdout"""
    from core.application.generation.prompt_builder import INSTRUCTION_FILES
    from core.application.rules.rules import RulesManager

    print("Active Rules & Project Instructions:")
    cwd = Path.cwd()

    items = []
    for name in INSTRUCTION_FILES:
        filepath = cwd / name
        if filepath.is_file():
            try:
                size = filepath.stat().st_size
                items.append(("file", name, filepath, size))
            except Exception:
                pass

    rules = RulesManager.get_instance().load_rules()
    for r in rules:
        items.append(("rule", r.name, r.source))

    if not items:
        print("  No rules or project instruction files found (AGENTS.md, CLAUDE.md, .cursorrules, .johnston/rules/).")
        return

    for idx, item in enumerate(items):
        if item[0] == "file":
            _, name, filepath, size = item
            print(f"  * {name} [project instruction]")
            print(f"    Path: {filepath} ({size} bytes)")
        else:
            _, r_name, r_source = item
            scope = f"[{r_source}]"
            print(f"  * {r_name} [rule] {scope}")
        if idx < len(items) - 1:
            print()


def print_roles():
    """Print available unified agent roles to stdout"""
    from core.role_registry import RoleRegistry

    registry = RoleRegistry.get_instance()
    roles = registry.load_roles()
    print("Available Agent Roles & Modes:")
    role_list = list(roles.items())
    for idx, (key, r) in enumerate(role_list):
        scope_str = f" [scope: {r.scope}]" if r.scope != "any" else ""
        print(f"  * {r.name} ({r.key}){scope_str} [{r.source}]")
        if r.description:
            print(f"    Description: {r.description}")
        if r.disallowed_tools:
            print(f"    Disallowed tools: {', '.join(r.disallowed_tools)}")
        if r.allowed_tools:
            print(f"    Allowed tools: {', '.join(r.allowed_tools)}")
        if idx < len(role_list) - 1:
            print()


def main():
    import argparse

    from core.infrastructure.platform.logging_setup import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(
        prog="johnston",
        description="Johnston Coding Agent",
    )
    parser.add_argument("--resume", help="Resume specific session ID")
    parser.add_argument("--models", action="store_true", help="List available providers and models")
    parser.add_argument("--skills", action="store_true", help="List available skills")
    parser.add_argument("--mcp", action="store_true", help="List configured MCP servers")
    parser.add_argument("--roles", action="store_true", help="List available agent roles (execution modes + subagents)")
    parser.add_argument("--rules", action="store_true", help="List active project instructions and rules")
    parser.add_argument("-v", "--version", action="store_true", help="Show application version")

    args = parser.parse_args()

    if args.version:
        print(f"johnston {get_version()}")
        sys.exit(0)

    if args.roles:
        print_roles()
        sys.exit(0)

    if args.models:
        print_models()
        sys.exit(0)

    if args.skills:
        print_skills()
        sys.exit(0)

    if args.mcp:
        print_mcp()
        sys.exit(0)

    if args.rules:
        print_rules()
        sys.exit(0)

    from app import JohnstonApp

    app = JohnstonApp(
        resume_session_id=args.resume,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        pass

    if getattr(app, "current_session_id", None) and hasattr(app, "sm"):
        try:
            sess = app.sm.get(app.current_session_id)
            if sess and (getattr(sess, "messages", None) or getattr(sess, "agent_history", None)):
                print(f"\nTo resume this session, run:\n  johnston --resume {app.current_session_id}")
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
