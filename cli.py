import asyncio
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None  # type: ignore

from core.provider_manager import ProviderManager


def get_version() -> str:
    """Get application version dynamically from metadata or pyproject.toml"""
    try:
        return version("johnston")
    except PackageNotFoundError:
        pyproject = Path(__file__).parent / "pyproject.toml"
        if pyproject.exists() and tomllib:
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "0.1.0-dev")
            except Exception:
                pass
        return "0.1.0-dev"


def print_models():
    """Print available providers and models to stdout"""
    pm = ProviderManager()
    providers = pm.load_providers()
    active_key = pm.get_active_provider_key()
    print("Available Johnston Providers & Models:\n")
    for key, info in providers.items():
        api_key = pm.get_api_key(key) or info.get("api_key", "")
        models = info.get("models") or ([info["model"]] if info.get("model") else [])
        if not api_key and not models:
            continue
        is_active = "*" if key == active_key else " "
        name = info.get("name") or info.get("NAME") or key
        model = info.get("model") or info.get("MODEL") or (models[0] if models else "not configured")
        key_status = "[key set]" if api_key else "[no key]"
        base_url = info.get("base_url") or info.get("BASE_URL") or ""

        print(f"{is_active} [{key}] {name} {key_status}")
        if model and model != "not configured":
            print(f"    Active Model: {model}")
        if models:
            print(f"    Models: {', '.join(models[:5])}{' ...' if len(models) > 5 else ''}")
        if base_url:
            print(f"    Base URL: {base_url}")
        print()


def print_skills():
    """Print available skills to stdout"""
    from core.skill_manager import SkillManager

    skills = SkillManager().list_skills()
    print("Available Johnston Skills:\n")
    if not skills:
        print("  No skills found (~/.johnston/skills/ or .johnston/skills/)")
        return
    for s in skills:
        scope = f"[{s.get('scope', 'global')}]"
        hidden = " [hidden]" if s.get("hidden") else ""
        name = s.get("name", "unnamed")
        print(f"  * {name} {scope}{hidden}")
        if s.get("path"):
            print(f"    Path: {s.get('path')}")
        print()


def print_mcp():
    """Print configured MCP servers to stdout"""
    from core.mcp_manager import get_mcp_manager

    mgr = get_mcp_manager()
    servers = mgr.load_servers()
    print("Configured MCP Servers:\n")
    if not servers:
        print("  No MCP servers configured (~/.johnston/mcp.json or .johnston/mcp.json)")
        return

    tools_by_server = {}
    try:
        active_tools = mgr.get_active_tools(mode="all")
        for t in active_tools:
            s_name = t.get("_mcp_server")
            t_name = t.get("_mcp_tool_name")
            if s_name and t_name:
                tools_by_server.setdefault(s_name, []).append(t_name)
    except Exception:
        pass

    for s in servers:
        disabled = s.get("disabled", False)
        status = "[disabled]" if disabled else "[active]"
        scope = f"[{s.get('scope', 'global')}]"
        mode = f"[{s.get('mode', 'eager')}]"
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

        print(f"  * {name} {scope} {mode} {status}")
        print(f"    {cmd_str}")

        if disabled:
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
        print()


def print_rules():
    """Print active project instructions and rules summary to stdout"""
    from core.rules_manager import RulesManager

    print("Active Rules & Project Instructions:\n")
    cwd = Path.cwd()
    instruction_files = ["AGENTS.md", "CLAUDE.md", ".cursorrules", ".windsurfrules", "CONVENTIONS.md"]
    found_any = False

    for name in instruction_files:
        filepath = cwd / name
        if filepath.is_file():
            try:
                size = filepath.stat().st_size
                print(f"  * {name} [project instruction]")
                print(f"    Path: {filepath} ({size} bytes)")
                print()
                found_any = True
            except Exception:
                pass

    rules = RulesManager.get_instance().load_rules()
    for r in rules:
        scope = f"[{r.source}]"
        print(f"  * {r.name} [rule] {scope}")
        if r.modes:
            print(f"    Modes: {', '.join(r.modes)}")
        if r.globs:
            print(f"    Globs: {', '.join(r.globs)}")
        print()
        found_any = True

    if not found_any:
        print("  No rules or project instruction files found (AGENTS.md, CLAUDE.md, .cursorrules, .rules/).")


def print_modes():
    """Print available agent execution modes to stdout"""
    from core.mode_manager import ModeManager

    modes = ModeManager.get_instance().load_modes()
    print("Available Agent Execution Modes:\n")
    for key, m in modes.items():
        ro_str = " (read-only)" if m.read_only else ""
        print(f"  • {m.name} ({m.key}){ro_str} [{m.source}]")
        if m.disallowed_tools:
            print(f"    Disallowed tools: {', '.join(m.disallowed_tools)}")
        print()


def print_subagents():
    """Print available subagent definitions and sessions to stdout"""
    from core.subagent_registry import SubagentRegistry
    from core.subagent_tracker import SubagentTracker

    registry = SubagentRegistry.get_instance()
    defs = registry.list_definitions()
    print("Available Subagent Definitions:")
    for dname, dval in defs.items():
        tools_str = f" | Tools: {', '.join(dval.tools)}" if dval.tools else ""
        model_str = f" | Model: {dval.model}" if dval.model else ""
        print(f"  • {dname} [{dval.source}]{tools_str}{model_str}")

    tracker = SubagentTracker.get_instance()
    sessions = list(tracker.sessions.values())
    if sessions:
        print("\nRegistered Subagent Sessions (last 10):")
        for sess in sessions[-10:]:
            print(
                f"  • ID: {sess.task_id} | Status: {sess.status.upper()} | Type: {sess.subagent_type} | Description: {sess.description}"
            )
    print()


def run_headless_prompt(
    prompt: str,
    mode: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    quiet: bool = False,
    verbose: bool = False,
):
    """Execute a single prompt headless via CLI with clean stdout piping and stderr tool logging"""
    pm = ProviderManager()
    if provider:
        pm.set_active_provider_key(provider)
    agent = pm.create_active_agent()
    if not agent:
        sys.stderr.write("Error: Could not initialize AI agent provider.\n")
        sys.exit(1)
    if model and agent:
        agent.model = model
    if mode and agent:
        agent.mode = mode

    async def _runner():
        last_printed_len = 0
        async for step in agent.stream_steps(prompt):
            chunk_type = step[0]
            val1 = step[1] if len(step) > 1 else ""
            val2 = step[2] if len(step) > 2 else ""

            if chunk_type in ("bot_delta", "bot_text", "text"):
                if len(val1) < last_printed_len:
                    last_printed_len = 0
                new_text = val1[last_printed_len:]
                if new_text:
                    sys.stdout.write(new_text)
                    sys.stdout.flush()
                    last_printed_len = len(val1)
            elif not quiet:
                if chunk_type in ("thinking_start", "thinking_delta") and verbose:
                    sys.stderr.write(f"\r[Thinking: {val1[:80]}...]\x1b[K")
                    sys.stderr.flush()
                elif chunk_type == "thinking_end" and verbose:
                    sys.stderr.write(f"\n[Thought for {val1}s]\n")
                    sys.stderr.flush()
                elif chunk_type == "tool":
                    last_printed_len = 0
                    sys.stderr.write(f"\n[Executing Tool: {val1} ({val2})]\n")
                    sys.stderr.flush()
                elif chunk_type == "tool_result" and verbose:
                    sys.stderr.write(f"[Tool Result: {str(val1)[:150]}...]\n")
                    sys.stderr.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

    asyncio.run(_runner())


def main():
    import argparse

    from app import JohnstonApp

    parser = argparse.ArgumentParser(
        prog="johnston",
        description="Johnston Coding Agent",
    )
    parser.add_argument("-p", "--prompt", help="Run a single prompt in CLI headless mode")
    parser.add_argument(
        "-m",
        "--mode",
        choices=["action", "explore"],
        help="Agent execution mode ('action' or 'explore')",
    )
    parser.add_argument("--provider", help="Set active provider key (e.g. openai)")
    parser.add_argument("--model", help="Set active model ID")
    parser.add_argument("--resume", help="Resume specific session ID")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress tool execution logs on stderr")
    parser.add_argument("--verbose", action="store_true", help="Show detailed thinking and tool output logs on stderr")
    parser.add_argument("--models", action="store_true", help="List available providers and models")
    parser.add_argument("--skills", action="store_true", help="List available skills")
    parser.add_argument("--mcp", action="store_true", help="List configured MCP servers")
    parser.add_argument("--modes", action="store_true", help="List available agent execution modes")
    parser.add_argument("--rules", action="store_true", help="List active project instructions and rules")
    parser.add_argument("--subagents", action="store_true", help="List available subagent definitions and sessions")
    parser.add_argument("--init", action="store_true", help="Initialize or update AGENTS.md guide for repo")
    parser.add_argument("-v", "--version", action="store_true", help="Show application version")

    args = parser.parse_args()

    if args.version:
        print(f"johnston {get_version()}")
        sys.exit(0)

    if args.modes:
        print_modes()
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

    if args.subagents:
        print_subagents()
        sys.exit(0)

    # Check for stdin piped input (e.g. cat file | johnston -p "...")
    stdin_input = ""
    if not sys.stdin.isatty():
        try:
            stdin_input = sys.stdin.read().strip()
        except Exception:
            pass

    target_prompt = args.prompt or ""
    if stdin_input:
        target_prompt = f"Piped Stdin Content:\n{stdin_input}\n\nTask: {target_prompt}".strip()

    if args.init:
        from core.commands import INIT_PROMPT_TEMPLATE

        run_headless_prompt(
            prompt=INIT_PROMPT_TEMPLATE,
            mode=args.mode,
            provider=args.provider,
            model=args.model,
            quiet=args.quiet,
            verbose=args.verbose,
        )
        sys.exit(0)

    if target_prompt:
        run_headless_prompt(
            prompt=target_prompt,
            mode=args.mode,
            provider=args.provider,
            model=args.model,
            quiet=args.quiet,
            verbose=args.verbose,
        )
        sys.exit(0)

    app = JohnstonApp(
        mode=args.mode,
        provider=args.provider,
        model=args.model,
        resume_session_id=args.resume,
    )
    app.run()

    if getattr(app, "current_session_id", None) and hasattr(app, "sm"):
        try:
            sess = app.sm.load_session(app.current_session_id)
            if sess and (sess.get("ui_messages") or sess.get("agent_history")):
                print(f"\nTo resume this session, run:\n  johnston --resume {app.current_session_id}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
