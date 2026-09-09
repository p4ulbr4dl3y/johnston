from johnston.tui.patch import apply_textual_patches

apply_textual_patches()

from pathlib import Path

from johnston.tui.app.app import JohnstonApp as JohnstonApp  # noqa: E402

_CSS_PATH = Path(__file__).resolve().parent / "app.tcss"
CSS_PATH = str(_CSS_PATH)

if __name__ == "__main__":
    from johnston.cli.main import main

    main()
