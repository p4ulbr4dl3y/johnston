from johnston_tui.patch import apply_textual_patches

apply_textual_patches()

from johnston_tui.app.app import JohnstonApp as JohnstonApp  # noqa: E402


def main() -> int:
    app = JohnstonApp()
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    from cli import main as cli_main

    cli_main()
