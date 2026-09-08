"""Main REPL execution loop for Johnston CLI."""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

from johnston_cli.repl.runner import AgentReplRunner
from johnston_cli.repl.session import create_repl_prompt_session, get_current_git_branch
from johnston_cli.repl.terminal import print_banner, print_top_separator
from johnston_core.interfaces.cli.entrypoint import get_version


async def run_repl_loop(
    initial_prompt: Optional[str] = None,
    args: Any = None,
) -> int:
    """Run interactive REPL loop until exit or interrupt."""
    model_override = getattr(args, "model", None) if args else None
    role_override = getattr(args, "role", None) if args else None

    runner = AgentReplRunner(model=model_override, role=role_override)
    branch = get_current_git_branch()
    version = get_version()
    display_model = f"{runner.provider_key}/{runner.model_name}"

    print_banner(version=version, model_name=display_model, branch=branch)

    session = create_repl_prompt_session()

    # Process initial prompt if passed via `j "prompt"`
    if initial_prompt and initial_prompt.strip():
        sys.stdout.write(f"\033[1;36m❯\033[0m {initial_prompt.strip()}\n\n")
        sys.stdout.flush()
        await runner.run_turn(initial_prompt.strip())

    while True:
        try:
            print_top_separator()
            text = await session.prompt_async([("class:prompt", "❯ ")])
            text = text.strip()
            print_top_separator()

            if not text:
                continue

            if text.lower() in ("exit", "quit", "/exit", "/quit"):
                sys.stdout.write("Goodbye!\n")
                break

            if text.lower() == "/help":
                sys.stdout.write(
                    "\nAvailable commands:\n"
                    "  exit, quit, /exit - Exit the CLI agent\n"
                    "  /help             - Show this help message\n\n"
                )
                sys.stdout.flush()
                continue

            await runner.run_turn(text)

        except (EOFError, KeyboardInterrupt):
            sys.stdout.write("\nGoodbye!\n")
            sys.stdout.flush()
            break
        except Exception as exc:
            sys.stderr.write(f"\n\033[31mError: {exc}\033[0m\n")
            sys.stderr.flush()

    return 0


def start_repl(initial_prompt: Optional[str] = None, args: Any = None) -> int:
    """Synchronous entrypoint for starting the REPL event loop."""
    try:
        return asyncio.run(run_repl_loop(initial_prompt=initial_prompt, args=args))
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        return 0
