from widgets.patch import apply_textual_patches

apply_textual_patches()

from widgets.app.app import JohnstonApp as JohnstonApp  # noqa: E402

if __name__ == "__main__":
    from cli import main

    main()
