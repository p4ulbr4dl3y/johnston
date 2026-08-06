"""Mock host app for visually inspecting subagent modals (SubagentsScreen / SubagentViewScreen).

Run: uv run python scripts/mock_subagents.py [--view] [--many]

Uses the real app.tcss and textual patches so the modal renders exactly
as inside JohnstonApp.
"""

import argparse
import os
import sys

from textual.app import App

from core.subagent_tracker import SubagentSessionData, SubagentTracker
from widgets.patch import apply_textual_patches
from widgets.screens.subagent_screen import SubagentViewScreen
from widgets.screens.subagents import SubagentsScreen

apply_textual_patches()

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.tcss")


def populate_mock_subagents(many: bool = False):
    tracker = SubagentTracker.get_instance()
    tracker.sessions.clear()

    # Subagent 1: Running
    s1 = SubagentSessionData(
        task_id="subagent-201",
        description="Search codebase for ModalScreen implementations",
        prompt="Grep codebase for ModalScreen and analyze styles",
        subagent_type="research",
        background=True,
        session_id=None,
    )
    s1.status = "running"
    s1.add_event({"type": "user_msg", "text": "Analyze ModalScreen styling across all widgets."})
    s1.add_event({"type": "thinking_delta", "text": "Searching files in widgets/screens..."})
    s1.add_event({"type": "tool_call", "name": "grep_search", "args": {"Query": "ModalScreen"}})
    s1.add_event({"type": "tool_result", "output": "Found 14 ModalScreen definitions."})
    s1.add_event({"type": "bot_msg", "text": "Analyzed 14 screens. All use unified `Label(id='modal-hint')`."})
    tracker.sessions["subagent-201"] = s1

    # Subagent 2: Completed
    s2 = SubagentSessionData(
        task_id="subagent-202",
        description="Audit TCSS margin and padding rules",
        prompt="Inspect app.tcss for vertical margin consistency",
        subagent_type="general",
        background=True,
        session_id=None,
    )
    s2.status = "completed"
    s2.add_event({"type": "user_msg", "text": "Audit app.tcss margins."})
    s2.add_event({"type": "bot_msg", "text": "1-line vertical rhythm established successfully."})
    tracker.sessions["subagent-202"] = s2

    if many:
        for i in range(3, 8):
            s = SubagentSessionData(
                task_id=f"subagent-20{i}",
                description=f"Automated refactoring task #{i}",
                prompt=f"Perform background cleanup step {i}",
                subagent_type="worker",
                background=True,
                session_id=None,
            )
            s.status = "running" if i % 2 == 0 else "completed"
            s.add_event({"type": "user_msg", "text": f"Running subagent #{i}"})
            s.add_event({"type": "bot_msg", "text": f"Subagent #{i} finished work."})
            tracker.sessions[f"subagent-20{i}"] = s


class MockHostApp(App[None]):
    CSS_PATH = CSS_PATH
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, screen_to_test, banner: str = ""):
        super().__init__()
        self.screen_to_test = screen_to_test
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
    p = argparse.ArgumentParser(description="Mock subagents modal for UI inspection")
    p.add_argument("--view", action="store_true", help="Show SubagentViewScreen instead of SubagentsScreen")
    p.add_argument("--many", action="store_true", help="Populate multiple mock subagents")
    return p


def main() -> int:
    args = build_parser().parse_args()
    populate_mock_subagents(many=args.many)

    if args.view:
        screen = SubagentViewScreen("subagent-201")
        banner = "SubagentViewScreen: subagent-201 (esc: cancel)"
    else:
        screen = SubagentsScreen()
        banner = f"SubagentsScreen: {len(SubagentTracker.get_instance().sessions)} tasks (enter: view details • k: kill • esc: cancel)"

    MockHostApp(screen, banner=banner).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
