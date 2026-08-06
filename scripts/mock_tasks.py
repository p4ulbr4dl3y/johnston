"""Mock host app for visually inspecting tasks modals (TasksListScreen / TaskConsoleScreen).

Run: uv run python scripts/mock_tasks.py [--console] [--many]

Uses the real app.tcss and textual patches so the modal renders exactly
as inside JohnstonApp.
"""

import argparse
import os
import sys
from typing import List

from textual.app import App

from widgets.patch import apply_textual_patches
from widgets.screens.tasks import TaskConsoleScreen, TasksListScreen

apply_textual_patches()

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.tcss")


class MockBackgroundTask:
    def __init__(self, task_id: str, command: str, is_running: bool, output: List[str], is_background: bool = True):
        self.task_id = task_id
        self.command = command
        self.is_running = is_running
        self.output = output
        self.is_background = is_background
        self.session_id = None

    def kill(self):
        self.is_running = False
        self.output.append("\n[Process terminated by user]")


MOCK_TASKS = [
    MockBackgroundTask(
        task_id="task-101",
        command="uv run pytest --maxfail=1",
        is_running=True,
        output=[
            "============================= test session starts ==============================",
            "platform darwin -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0",
            "rootdir: /Users/yegor/johnston",
            "collected 616 items",
            "",
            "tests/core/test_cli.py ........... [ 10%]",
            "tests/ui/test_screens.py ........................... [ 45%]",
            "tests/ui/test_ask_user_screen.py ................. [ 75%]",
            "tests/ui/test_tasks.py ... [ 85%]",
            "Running remaining test suites...",
        ],
    ),
    MockBackgroundTask(
        task_id="task-102",
        command="npm run build",
        is_running=False,
        output=[
            "> johnston-ui@1.0.0 build",
            "> vite build",
            "",
            "building for production...",
            "dist/index.html   0.45 kB",
            "dist/assets/index.js 124.50 kB",
            "✓ built in 1.25s",
        ],
    ),
    MockBackgroundTask(
        task_id="task-103",
        command="uv sync --all-extras",
        is_running=True,
        output=[
            "Auditing dependencies...",
            "Resolved 42 packages in 120ms",
            "Installing textual>=0.80.0...",
            "Downloading wheel for textual...",
            "Installing packages...",
        ],
    ),
]


class MockHostApp(App[None]):
    CSS_PATH = CSS_PATH
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, screen_to_test, tasks: List[MockBackgroundTask], banner: str = ""):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.background_tasks = tasks
        self.current_session_id = None
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
    p = argparse.ArgumentParser(description="Mock tasks modal for UI inspection")
    p.add_argument("--console", action="store_true", help="Show TaskConsoleScreen instead of TasksListScreen")
    p.add_argument("--many", action="store_true", help="Include additional mock tasks")
    return p


def main() -> int:
    args = build_parser().parse_args()
    tasks = list(MOCK_TASKS)

    if args.many:
        for i in range(4, 9):
            tasks.append(
                MockBackgroundTask(
                    task_id=f"task-10{i}",
                    command=f"python scripts/worker_{i}.py --batch-size 64",
                    is_running=(i % 2 == 0),
                    output=[f"Worker {i} initialized", f"Processing chunk {i * 10}..."],
                )
            )

    if args.console:
        screen = TaskConsoleScreen(tasks[0])
        banner = f"TaskConsoleScreen: {tasks[0].task_id} ({tasks[0].command}) (esc: cancel)"
    else:
        screen = TasksListScreen()
        banner = f"TasksListScreen: {len(tasks)} tasks (enter: view output • k: kill task • esc: cancel)"

    MockHostApp(screen, tasks=tasks, banner=banner).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
