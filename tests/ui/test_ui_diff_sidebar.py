"""Diff sidebar labels must stay unambiguous in a narrow column (P2-13).

The sidebar showed only `os.path.basename(...)`, so two `test_foo.py` files in
different folders rendered as the same row with no way to tell them apart.
"""

import os

import pytest

from rich.text import Text

from widgets.presentation.screens.diff import DiffScreen
from widgets.utils.row_format import display_width, middle_ellipsize

STAT = "+1/-2"  # the stats column built by _format_sidebar_options for (1, 2)
STAT_WIDTH = len(STAT)


def _labels(paths, width: int = 31) -> list[str]:
    """Plain-text file column of each sidebar row (the stat column is dropped)."""
    screen = DiffScreen([(path, "diff --git a/x b/x", 1, 2) for path in paths])
    rows = (Text.from_markup(row).plain for row in screen._format_sidebar_options(width))
    # The stat column is a fixed "+1/-2" tail; drop it to get the file column.
    return [row[: -len(STAT)].rstrip() for row in rows]


def test_same_named_files_are_distinguishable():
    labels = _labels(["tests/ui/test_foo.py", "widgets/ui/test_foo.py"])
    assert labels[0] != labels[1], labels
    assert labels[0].endswith("test_foo.py") and labels[1].endswith("test_foo.py")
    assert "tests" in labels[0] and "widgets" in labels[1]


def test_absolute_paths_are_shown_relative_to_the_workspace():
    cwd = os.getcwd()
    labels = _labels([os.path.join(cwd, "widgets/status_footer.py")])
    assert labels[0] == "widgets/status_footer.py", labels


def test_paths_outside_the_workspace_are_kept_as_is():
    labels = _labels(["/etc/hosts"])
    assert labels[0] == "/etc/hosts", labels


def test_labels_fit_the_sidebar_width():
    long_path = "/".join(["segment-with-a-long-name"] * 6) + "/file_name.py"
    for width in (22, 26, 31):
        for label in _labels([long_path], width=width):
            assert display_width(label) + STAT_WIDTH + 1 <= width, (label, width)


def test_middle_ellipsis_keeps_both_ends():
    assert middle_ellipsize("tests/ui/test_foo.py", 14) == "te…test_foo.py"
    assert middle_ellipsize("short.py", 20) == "short.py"
    assert middle_ellipsize("a.py", 1) == "…"


@pytest.mark.asyncio
async def test_sidebar_rows_render_distinctly():
    from app import JohnstonApp
    from textual.widgets import OptionList

    app = JohnstonApp()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause(0.3)
        screen = DiffScreen(
            [
                ("tests/ui/test_foo.py", "diff --git a/x b/x", 3, 1),
                ("widgets/ui/test_foo.py", "diff --git a/y b/y", 2, 5),
            ]
        )
        app.push_screen(screen)
        await pilot.pause(0.5)
        opt_list = screen.query_one("#diff-file-list", OptionList)
        prompts = [str(option.prompt) for option in opt_list.options]
        assert len(prompts) == 2
        assert prompts[0] != prompts[1]
