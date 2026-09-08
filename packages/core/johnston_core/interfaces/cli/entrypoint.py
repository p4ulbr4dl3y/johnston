"""Main CLI entrypoint and argument parser dispatch for Johnston."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from johnston_core.infrastructure.platform.logging_setup import setup_logging
from johnston_core.interfaces.cli.commands.mcp_cmd import print_mcp
from johnston_core.interfaces.cli.commands.provider_cmd import print_models

__all__ = ["build_parser", "get_version", "main", "print_mcp", "print_models"]



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
    from johnston_core.interfaces.cli.commands.roles_cmd import run_roles
    return run_roles(args)


def _dispatch_skills(args: Any = None) -> int:
    from johnston_core.interfaces.cli.commands.skills_cmd import run_skills
    return run_skills(args)


def _dispatch_rules(args: Any = None) -> int:
    from johnston_core.interfaces.cli.commands.rules_cmd import run_rules
    return run_rules(args)


def build_parser() -> argparse.ArgumentParser:
    """Build root ArgumentParser with subcommands and backward-compatible flags."""
    parser = argparse.ArgumentParser(
        prog="johnston",
        description="Johnston Coding Agent",
    )
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_latest",
        action="store_true",
        help="Resume most recent session",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        default=None,
        help="Resume specific session ID (or pick from list if ID omitted)",
    )
    parser.add_argument("-p", "--prompt", default=None, help="Initial prompt to post on start")
    parser.add_argument("-m", "--model", default=None, help="Override active model")
    parser.add_argument("-r", "--role", default=None, help="Initial agent role")
    parser.add_argument(
        "--mode",
        choices=["review", "edits", "yolo"],
        default=None,
        help="Initial permission mode",
    )
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high"],
        default=None,
        help="Thinking/reasoning effort",
    )
    sandbox_grp = parser.add_mutually_exclusive_group()
    sandbox_grp.add_argument("--sandbox", action="store_true", help="Enable execution sandbox")
    sandbox_grp.add_argument("--no-sandbox", action="store_true", help="Disable execution sandbox")
    parser.add_argument(
        "-w",
        "--workspace",
        action="append",
        default=[],
        help="Additional allowed workspace root directory",
    )
    parser.add_argument("-C", "--cwd", default=None, help="Change working directory")
    parser.add_argument("-b", "--branch", default=None, help="Switch to git branch in an isolated worktree")
    parser.add_argument("--theme", default=None, help="UI theme override")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging level")
    parser.add_argument("-v", "--version", action="store_true", help="Show application version")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # config subparser
    config_p = subparsers.add_parser("config", help="Inspect and modify application settings")
    config_subs = config_p.add_subparsers(dest="config_action", help="Config actions")

    cfg_list = config_subs.add_parser("list", help="List all configuration settings")
    cfg_list.add_argument("--json", action="store_true", help="Print structured JSON output")

    get_p = config_subs.add_parser("get", help="Get a configuration setting value")
    get_p.add_argument("key", help="Configuration key (e.g. llm.context_limit, theme)")
    get_p.add_argument("--json", action="store_true", help="Print structured JSON output")

    set_p = config_subs.add_parser("set", help="Set a configuration setting value")
    set_p.add_argument("key", help="Configuration key (e.g. llm.context_limit, theme)")
    set_p.add_argument("value", help="Configuration value to set")

    unset_p = config_subs.add_parser("unset", help="Reset a configuration setting to default")
    unset_p.add_argument("key", help="Configuration key (e.g. llm.context_limit, theme)")

    # provider subparser
    provider_p = subparsers.add_parser("provider", help="Manage LLM providers and models")
    provider_subs = provider_p.add_subparsers(dest="provider_action", help="Provider actions")

    prov_list = provider_subs.add_parser("list", help="List configured providers and models")
    prov_list.add_argument("--json", action="store_true", help="Print structured JSON output")

    sk_p = provider_subs.add_parser("set-key", help="Set API key for a provider")
    sk_p.add_argument("name", help="Provider name or key")
    sk_p.add_argument("key", nargs="?", default=None, help="API key to save")

    sm_p = provider_subs.add_parser("set-model", help="Set active model for a provider")
    sm_p.add_argument("name", help="Provider name or key")
    sm_p.add_argument("model", help="Model name to set")

    en_p = provider_subs.add_parser("enable", help="Enable a provider")
    en_p.add_argument("name", help="Provider name or key")

    dis_p = provider_subs.add_parser("disable", help="Disable a provider")
    dis_p.add_argument("name", help="Provider name or key")

    add_p = provider_subs.add_parser("add", help="Add a new provider to providers.json")
    add_p.add_argument("name", help="Provider name or key")
    add_p.add_argument("--model", required=True, help="Default model for provider")
    add_p.add_argument("--api-key", default=None, help="API key for provider")
    add_p.add_argument("--base-url", default=None, help="Base URL for provider API")

    rm_p = provider_subs.add_parser("rm", help="Remove a provider from providers.json")
    rm_p.add_argument("name", help="Provider name or key")

    # mcp subparser
    mcp_p = subparsers.add_parser("mcp", help="Manage Model Context Protocol (MCP) servers")
    mcp_subs = mcp_p.add_subparsers(dest="mcp_action", help="MCP actions")

    mcp_list = mcp_subs.add_parser("list", help="List configured MCP servers")
    mcp_list.add_argument("--json", action="store_true", help="Print structured JSON output")

    mcp_add = mcp_subs.add_parser("add", help="Add or update an MCP server")
    mcp_add.add_argument("name", help="Server name")
    cmd_or_url = mcp_add.add_mutually_exclusive_group(required=True)
    cmd_or_url.add_argument("--cmd", dest="cmd", help="Command to run the stdio MCP server")
    cmd_or_url.add_argument("--url", dest="url", help="HTTP/SSE URL for the MCP server")
    mcp_add.add_argument("--args", nargs="*", default=None, help="Arguments for the command")
    mcp_add.add_argument("--scope", choices=["global", "project"], default="global", help="Scope (global or project)")

    mcp_rm = mcp_subs.add_parser("rm", help="Remove an MCP server")
    mcp_rm.add_argument("name", help="Server name")
    mcp_rm.add_argument("--scope", choices=["global", "project"], default=None, help="Scope (global or project)")

    mcp_en = mcp_subs.add_parser("enable", help="Enable an MCP server")
    mcp_en.add_argument("name", help="Server name")
    mcp_en.add_argument("--scope", choices=["global", "project"], default=None, help="Scope (global or project)")

    mcp_dis = mcp_subs.add_parser("disable", help="Disable an MCP server")
    mcp_dis.add_argument("name", help="Server name")
    mcp_dis.add_argument("--scope", choices=["global", "project"], default=None, help="Scope (global or project)")

    # roles subparser
    roles_p = subparsers.add_parser("roles", help="List available agent roles (execution modes + subagents)")
    roles_p.add_argument("--json", action="store_true", help="Print structured JSON output")

    # skills subparser
    skills_p = subparsers.add_parser("skills", help="List available skills")
    skills_p.add_argument("--json", action="store_true", help="Print structured JSON output")

    # rules subparser
    rules_p = subparsers.add_parser("rules", help="List active project instructions and rules")
    rules_p.add_argument("--json", action="store_true", help="Print structured JSON output")

    # session subparser
    session_p = subparsers.add_parser("session", help="Manage chat sessions")
    session_subs = session_p.add_subparsers(dest="session_action", help="Session actions")

    sess_list = session_subs.add_parser("list", help="List chat sessions")
    sess_list.add_argument("--limit", type=int, default=20, help="Maximum number of sessions to list (default: 20)")
    sess_list.add_argument("--all", action="store_true", help="List all sessions without limit")
    sess_list.add_argument("--json", action="store_true", help="Print structured JSON output")

    sess_rm = session_subs.add_parser("rm", help="Remove a session by ID")
    sess_rm.add_argument("session_id", help="Session ID to remove")

    sess_prune = session_subs.add_parser("prune", help="Prune old sessions")
    sess_prune.add_argument("--days", type=int, default=14, help="Prune sessions older than N days (default: 14)")

    sess_export = session_subs.add_parser("export", help="Export session dialogue")
    sess_export.add_argument("session_id", help="Session ID to export")
    sess_export.add_argument(
        "--format",
        dest="format",
        choices=["md", "json"],
        default="md",
        help="Export format (md or json, default: md)",
    )
    sess_export.add_argument("--output", default=None, help="Output file path (default: stdout)")

    # doctor subparser
    doctor_p = subparsers.add_parser("doctor", help="Check environment and configuration health")
    doctor_p.add_argument("--json", action="store_true", help="Print structured JSON output")

    # run subparser
    run_p = subparsers.add_parser("run", help="Run prompt headlessly and stream response")
    run_p.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Prompt to execute (use '-' to read from stdin)",
    )
    run_p.add_argument(
        "-c",
        "--continue",
        dest="continue_latest",
        action="store_true",
        help="Resume most recent session",
    )
    run_p.add_argument(
        "--resume",
        nargs="?",
        const="",
        default=None,
        help="Resume session ID (latest if omitted)",
    )
    run_p.add_argument("--provider", default=None, help="Override active provider")
    run_p.add_argument("--model", default=None, help="Override active model")
    run_p.add_argument("--role", default="worker", help="Agent execution role (default: worker)")
    run_p.add_argument(
        "--effort",
        choices=["low", "medium", "high"],
        default=None,
        help="Thinking/reasoning effort",
    )
    run_p.add_argument(
        "--mode",
        choices=["review", "edits", "yolo"],
        default=None,
        help="Permission mode (review, edits, yolo)",
    )
    run_p.add_argument(
        "-y",
        "--yolo",
        action="store_true",
        help="Shortcut for --mode yolo (allow all tool actions without confirmation)",
    )
    run_sandbox = run_p.add_mutually_exclusive_group()
    run_sandbox.add_argument("--sandbox", action="store_true", help="Enable execution sandbox")
    run_sandbox.add_argument("--no-sandbox", action="store_true", help="Disable execution sandbox")
    run_p.add_argument(
        "-w",
        "--workspace",
        action="append",
        default=[],
        help="Additional allowed workspace root directory",
    )
    run_p.add_argument("-C", "--cwd", default=None, help="Change working directory")
    run_p.add_argument("-b", "--branch", default=None, help="Switch to git branch in an isolated worktree")
    run_p.add_argument(
        "-s",
        "--skill",
        dest="skills",
        action="append",
        default=[],
        help="Activate skill(s) by name (can be specified multiple times)",
    )
    run_p.add_argument("--debug", action="store_true", help="Enable DEBUG logging level")
    run_p.add_argument("--json", action="store_true", help="Print structured JSON output")
    run_p.add_argument("--stream-json", action="store_true", help="Stream real-time NDJSON events")
    run_p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only assistant text without tool call status headers",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for Johnston CLI."""
    setup_logging()

    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "debug", False):
        logging.getLogger().setLevel(logging.DEBUG)

    if getattr(args, "cwd", None):
        cwd_dir = os.path.abspath(args.cwd)
        if not os.path.isdir(cwd_dir):
            sys.stderr.write(f"Error: Directory '{args.cwd}' does not exist.\n")
            sys.exit(1)
        os.chdir(cwd_dir)

    for ws in getattr(args, "workspace", []) or []:
        if ws:
            from johnston_core.permission_manager import PermissionManager

            PermissionManager.get_instance().add_workspace_root(ws)

    if args.version:
        print(f"johnston {_dispatch_version()}")
        sys.exit(0)

    branch_wt_path = None
    branch_name = None
    if getattr(args, "branch", None):
        raw_b = args.branch.strip()
        if raw_b:
            from johnston_core.infrastructure.runtime.git_worktree import GitWorktreeManager
            from johnston_core.permission_manager import PermissionManager

            cur_dir = os.getcwd()
            if not GitWorktreeManager.is_git_repo(cur_dir):
                sys.stderr.write(f"Error: Directory '{cur_dir}' is not a git repository.\n")
                sys.exit(1)
            repo_root = GitWorktreeManager.get_repo_root(cur_dir)
            wt_path, actual_b = GitWorktreeManager.create_worktree(repo_root, raw_b)
            if not wt_path or not os.path.exists(wt_path):
                sys.stderr.write(f"Error: Failed to create or attach worktree for branch '{raw_b}'.\n")
                sys.exit(1)
            os.chdir(wt_path)
            PermissionManager.get_instance().set_project_dir(wt_path)
            branch_wt_path = wt_path
            branch_name = actual_b

    # Subcommands
    if args.subcommand == "config":
        from johnston_core.interfaces.cli.commands.config_cmd import run_config

        code = run_config(args)
        sys.exit(code)
    elif args.subcommand == "provider":
        from johnston_core.interfaces.cli.commands.provider_cmd import run_provider

        code = run_provider(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "mcp":
        from johnston_core.interfaces.cli.commands.mcp_cmd import run_mcp

        code = run_mcp(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "roles":
        code = _dispatch_roles(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "skills":
        code = _dispatch_skills(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "rules":
        code = _dispatch_rules(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "session":
        from johnston_core.interfaces.cli.commands.session_cmd import run_session

        code = run_session(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "doctor":
        from johnston_core.interfaces.cli.commands.doctor_cmd import run_doctor

        code = run_doctor(args)
        sys.exit(code if code is not None else 0)
    elif args.subcommand == "run":
        from johnston_core.interfaces.cli.commands.run_cmd import run_headless

        code = run_headless(args)
        sys.exit(code if code is not None else 0)

    from app import JohnstonApp

    sandbox_val = True if getattr(args, "sandbox", False) else (False if getattr(args, "no_sandbox", False) else None)
    app = JohnstonApp(
        resume_session_id=getattr(args, "resume", None),
        continue_latest=getattr(args, "continue_latest", False),
        initial_prompt=getattr(args, "prompt", None),
        model=getattr(args, "model", None),
        role=getattr(args, "role", None),
        mode=getattr(args, "mode", None),
        effort=getattr(args, "effort", None),
        sandbox=sandbox_val,
        theme=getattr(args, "theme", None),
    )
    if branch_wt_path and branch_name and hasattr(app, "switch_project_dir"):
        app.switch_project_dir(branch_wt_path, branch_name)
    try:
        app.run()
    except KeyboardInterrupt:
        pass

    _print_resume_hint(app)
    sys.exit(0)

