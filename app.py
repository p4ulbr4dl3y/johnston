from johnston_tui.patch import apply_textual_patches

apply_textual_patches()

from johnston_tui.app import JohnstonApp as JohnstonApp  # noqa: E402

if __name__ == "__main__":
    from cli import main

    main()
