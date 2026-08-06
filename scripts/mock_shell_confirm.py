"""Mock host app for visually inspecting the shell confirmation modal (ShellConfirmScreen).

Run: uv run python scripts/mock_shell_confirm.py [--long]

Uses the real app.tcss and textual patches so the modal renders exactly
as inside JohnstonApp.
"""

import argparse
import os
import sys

from textual.app import App

from widgets.patch import apply_textual_patches
from widgets.screens.shell_confirm import ShellConfirmScreen

apply_textual_patches()

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.tcss")


class MockHostApp(App[None]):
    CSS_PATH = CSS_PATH
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, screen_to_test, banner: str = ""):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.banner = banner

    def on_mount(self) -> None:
        if self.banner:
            sys.stdout.write(f"\n{self.banner}\n")
            sys.stdout.flush()

        def on_dismiss(result) -> None:
            print(f"\n[modal dismissed] result: {result!r}")
            self.exit()

        self.push_screen(self.screen_to_test, callback=on_dismiss)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Mock ShellConfirmScreen for UI inspection")
    p.add_argument("--long", action="store_true", help="Show long multi-line command")
    return p


def main() -> int:
    args = build_parser().parse_args()

    if args.long:
        cmd = (
            "find . -name '*.pyc' -delete && \\\n"
            "rm -rf build/ dist/ *.egg-info && \\\n"
            "git clean -fdx --exclude='.env' && \\\n"
            "uv run pytest --maxfail=1"
        )
    else:
        cmd = "rm -rf /tmp/staging_cache_dir"

    screen = ShellConfirmScreen(cmd)
    banner = f"ShellConfirmScreen: {cmd!r} (enter: confirm • esc: cancel)"
    MockHostApp(screen, banner=banner).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
