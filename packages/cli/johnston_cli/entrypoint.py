"""Unified CLI entrypoint for Johnston (`johnston` and `j`)."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Sequence

from johnston_cli.repl import start_repl
from johnston_core.infrastructure.platform.logging_setup import setup_logging
from johnston_core.interfaces.cli.commands.config_cmd import run_config
from johnston_core.interfaces.cli.commands.doctor_cmd import run_doctor
from johnston_core.interfaces.cli.commands.mcp_cmd import print_mcp, run_mcp
from johnston_core.interfaces.cli.commands.provider_cmd import print_models, run_provider
from johnston_core.interfaces.cli.commands.roles_cmd import print_roles, run_roles
from johnston_core.interfaces.cli.commands.rules_cmd import print_rules, run_rules
from johnston_core.interfaces.cli.commands.run_cmd import run_headless
from johnston_core.interfaces.cli.commands.session_cmd import run_session
from johnston_core.interfaces.cli.commands.skills_cmd import print_skills, run_skills
from johnston_core.interfaces.cli.entrypoint import (
    _print_resume_hint,
    get_version,
)
from johnston_core.interfaces.cli.entrypoint import (
    build_parser as _core_build_parser,
)

__all__ = [
    "build_parser",
    "get_version",
    "main",
    "main_j",
    "main_johnston",
    "print_mcp",
    "print_models",
    "print_roles",
    "print_rules",
    "print_skills",
]


KNOWN_SUBCOMMANDS = {
    "config",
    "doctor",
    "mcp",
    "provider",
    "roles",
    "rules",
    "run",
    "session",
    "skills",
}

FLAGS_WITH_VALUE = {
    "-p",
    "--prompt",
    "-m",
    "--model",
    "-r",
    "--role",
    "--mode",
    "--effort",
    "-w",
    "--workspace",
    "-C",
    "--cwd",
    "-b",
    "--branch",
    "--theme",
    "--resume",
}


def build_parser(prog: str = "johnston") -> argparse.ArgumentParser:
    """Build unified ArgumentParser configured for the specified command name."""
    parser = _core_build_parser()
    parser.prog = prog
    if prog == "j":
        parser.description = "Johnston Interactive Agent CLI"
    else:
        parser.description = "Johnston Coding Agent (TUI & CLI)"
    return parser


def _normalize_j_argv(argv: Sequence[str] | None) -> list[str]:
    """Extract positional prompt from `j` invocation if not matching subcommands."""
    if argv is None:
        raw = sys.argv[1:]
    else:
        raw = list(argv)

    new_args: list[str] = []
    positionals: list[str] = []
    i = 0
    has_subcommand = False
    has_explicit_prompt = False

    while i < len(raw):
        arg = raw[i]
        if arg in ("-p", "--prompt"):
            has_explicit_prompt = True
            new_args.append(arg)
            if i + 1 < len(raw):
                new_args.append(raw[i + 1])
                i += 2
                continue
            i += 1
            continue

        if arg in FLAGS_WITH_VALUE:
            new_args.append(arg)
            if i + 1 < len(raw):
                new_args.append(raw[i + 1])
                i += 2
                continue
            i += 1
            continue

        if arg.startswith("-"):
            new_args.append(arg)
            i += 1
            continue

        if arg in KNOWN_SUBCOMMANDS:
            has_subcommand = True
            new_args.extend(raw[i:])
            break
        else:
            positionals.append(arg)
            i += 1

    if positionals and not has_subcommand and not has_explicit_prompt:
        joined = " ".join(positionals).strip()
        if joined:
            new_args.extend(["-p", joined])

    return new_args


def _dispatch_common_flags(args: Any) -> None:
    """Handle global setup flags before dispatching subcommands or UI."""
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

    if getattr(args, "version", False):
        print(f"{getattr(args, 'prog', 'johnston')} {get_version()}")
        sys.exit(0)


def _handle_worktree_branch(branch_arg: str | None) -> tuple[str | None, str | None]:
    """Switch project directory to isolated worktree if branch specified."""
    if not branch_arg or not branch_arg.strip():
        return None, None
    raw_b = branch_arg.strip()
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
    return wt_path, actual_b


def _dispatch_subcommands(args: Any) -> int | None:
    """Execute subcommand if requested. Returns exit code or None if no subcommand."""
    sub = getattr(args, "subcommand", None)
    if sub == "config":
        return run_config(args)
    elif sub == "provider":
        code = run_provider(args)
        return code if code is not None else 0
    elif sub == "mcp":
        code = run_mcp(args)
        return code if code is not None else 0
    elif sub == "roles":
        code = run_roles(args)
        return code if code is not None else 0
    elif sub == "skills":
        code = run_skills(args)
        return code if code is not None else 0
    elif sub == "rules":
        code = run_rules(args)
        return code if code is not None else 0
    elif sub == "session":
        code = run_session(args)
        return code if code is not None else 0
    elif sub == "doctor":
        code = run_doctor(args)
        return code if code is not None else 0
    elif sub == "run":
        code = run_headless(args)
        return code if code is not None else 0
    return None


def main_johnston(argv: Sequence[str] | None = None) -> int:
    """Main entrypoint for `johnston` command (TUI default, subcommands supported)."""
    setup_logging()
    parser = build_parser(prog="johnston")
    args = parser.parse_args(argv)

    _dispatch_common_flags(args)
    branch_wt_path, branch_name = _handle_worktree_branch(getattr(args, "branch", None))

    sub_code = _dispatch_subcommands(args)
    if sub_code is not None:
        return sub_code

    try:
        from johnston_tui.app import JohnstonApp
    except ImportError:
        try:
            from app import JohnstonApp
        except ImportError:
            sys.stderr.write("Error: Johnston TUI is not installed.\n")
            return 1

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
    return 0


def main_j(argv: Sequence[str] | None = None) -> int:
    """Main entrypoint for `j` command (Interactive REPL default, prompt runner)."""
    setup_logging()
    norm_argv = _normalize_j_argv(argv)
    parser = build_parser(prog="j")
    args = parser.parse_args(norm_argv)

    _dispatch_common_flags(args)
    _handle_worktree_branch(getattr(args, "branch", None))

    sub_code = _dispatch_subcommands(args)
    if sub_code is not None:
        return sub_code

    prompt = getattr(args, "prompt", None)
    has_stdin_data = False
    if not sys.stdin.isatty():
        import select

        try:
            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            has_stdin_data = bool(r)
        except Exception:
            has_stdin_data = False

    if has_stdin_data or (prompt and not sys.stdin.isatty()):
        if prompt:
            args.headless_prompt = prompt
        return run_headless(args)

    return start_repl(initial_prompt=prompt, args=args)


def main(argv: Sequence[str] | None = None) -> int:
    """Default entrypoint delegating to main_johnston."""
    return main_johnston(argv)
