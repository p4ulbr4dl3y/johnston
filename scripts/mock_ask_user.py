"""Mock host app for visually inspecting the ask_user modal (AskUserWizardScreen / ConfirmScreen).

Run: uv run python scripts/mock_ask_user.py [--confirm] [--many]

Uses the real app.tcss and textual patches so the modal renders exactly
as inside JohnstonApp.
"""

import argparse
import os
import sys

from textual.app import App

from widgets.patch import apply_textual_patches

apply_textual_patches()

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.tcss")

DEMO_QUESTIONS = [
    {
        "question_text": "Что хочешь сделать с этим багом?",
        "options": [
            "(Recommended) Починить сразу",
            "Сначала написать тест",
            "Только посмотреть код",
            "Отложить до завтра",
        ],
    },
    {
        "question_text": "Какой провайдер использовать?",
        "options": [
            "openai",
            "anthropic",
            "gemini",
            "local",
        ],
    },
    {
        "question_text": "Опиши свободным текстом, что именно сломано. Enter — подтвердить.",
        "options": [],
    },
]

MANY_QUESTIONS = DEMO_QUESTIONS + [
    {
        "question_text": f"Длинный вопрос {i}: выбери один вариант из списка, прокрути если нужно.",
        "options": [f"Вариант {j}" for j in range(1, 16)],
    }
    for i in range(1, 4)
]


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
    p = argparse.ArgumentParser(description="Mock ask_user modal for UI inspection")
    p.add_argument("--confirm", action="store_true", help="Show ConfirmScreen instead of the wizard")
    p.add_argument("--many", action="store_true", help="Use a long multi-question wizard (scroll/overflow testing)")
    return p


def main() -> int:
    args = build_parser().parse_args()

    if args.confirm:
        from widgets.screens.ask_user import ConfirmScreen

        screen = ConfirmScreen(
            "**Question 1:** Что хочешь сделать с этим багом?\n\n"
            "**Answer:** Починить сразу\n\n"
            "**Question 2:** Какой провайдер использовать?\n\n"
            "**Answer:** openai\n"
        )
        banner = "ConfirmScreen (enter: confirm • ←: back • esc: cancel)"
    else:
        from widgets.screens.ask_user import AskUserWizardScreen

        questions = MANY_QUESTIONS if args.many else DEMO_QUESTIONS
        screen = AskUserWizardScreen(questions)
        banner = (
            f"AskUserWizardScreen: {len(questions)} questions "
            "(enter: confirm • space: toggle • ←: back • →: next • esc: cancel)"
        )

    MockHostApp(screen, banner=banner).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
