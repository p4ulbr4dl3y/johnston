"""Regression: the status footer must never clip a row silently.

`StatusFooter` renders two fixed-height lines. With a Rich ``Table.grid`` the
left column only received ~half the terminal, so on 75-99 column terminals the
second row wrapped and its tail (branch, execution mode) was dropped without an
ellipsis. Rows are now fitted to the widget width instead.
"""

from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from rich.text import Text

from widgets.status_footer import StatusFooter

STATUS_KWARGS = dict(
    provider_key="openai",
    provider_display="OpenAI",
    is_connected=True,
    model_name="gpt-4o",
    clean_model="GPT 4o",
    agent_role="worker",
    directory="/home/user/johnston",
    context_used=0,
    context_limit=128000,
    total_tokens=0,
    cost_usd=0.0,
    execution_mode="review",
)
WIDTHS = (40, 60, 70, 76, 80, 88, 90, 98, 100, 120, 140, 200)


class FooterHarness(StatusFooter):
    """StatusFooter bound to a synthetic width, without a live app."""

    def __init__(self, width: int) -> None:
        super().__init__()
        self._width = width
        self.last_update = None

    @property
    def app(self):
        return None

    @property
    def size(self):
        return SimpleNamespace(width=self._width, height=3)

    def update(self, renderable=None) -> None:  # type: ignore[override]
        self.last_update = renderable

    def _git_branch(self, cwd=None) -> str:
        return "arena/01a05e32-johnston"

    def _git_diff_stats(self, cwd=None) -> str:
        return ""


def _rows(width: int) -> list[str]:
    footer = FooterHarness(width)
    footer.update_status(**STATUS_KWARGS)
    rendered = footer.last_update
    assert isinstance(rendered, Text), type(rendered)
    return rendered.plain.split("\n")


@pytest.mark.parametrize("width", WIDTHS, ids=str)
def test_footer_rows_fit_available_width(width):
    content_width = max(10, width - 2)
    for line in _rows(width):
        assert cell_len(line) <= content_width, f"width={width}: row overflows: {line!r}"


@pytest.mark.parametrize("width", (70, 76, 80, 88, 90, 98, 100), ids=str)
def test_footer_keeps_mode_and_branch_on_common_widths(width):
    # Regression: branch + execution mode silently disappeared at 80-99 columns.
    row2 = _rows(width)[1]
    assert "johnston" in row2
    assert "review" in row2, f"width={width}: execution mode dropped: {row2!r}"
    assert "arena/01a05e32-johnston" in row2 or "..." in row2
    assert not row2.rstrip().endswith("•"), f"width={width}: dangling separator: {row2!r}"


def test_footer_shrinks_with_ellipsis_instead_of_clipping():
    narrow = _rows(60)[1]
    assert "..." in narrow or "…" in narrow
    wide = _rows(140)[1]
    assert "..." not in wide


def test_footer_row_one_keeps_metrics_when_space_is_tight():
    for width in (40, 60):
        row1, _ = _rows(width)
        assert "GPT 4o" in row1
        assert cell_len(row1) <= max(10, width - 2)


def test_footer_degrades_when_env_row_is_overloaded():
    """Worst case (git diff + sandbox + mode on an 80 column terminal): the row
    must still fit and end with an ellipsis, never with a bare separator."""
    # Workspace outside $HOME so the path is never collapsed to "~/...".
    directory = "/workspace/very-long-project-directory-name/johnston-service"
    footer = FooterHarness(80)
    footer._git_diff_stats = lambda cwd=None: "+12/-4"
    footer.update_status(**{**STATUS_KWARGS, "directory": directory, "sandbox_enabled": True})
    row2 = footer.last_update.plain.split("\n")[1]
    assert cell_len(row2) <= 78
    body = row2.rstrip()
    assert body.endswith("…") or body.endswith("...")
    assert not body.endswith("•")
    assert "johnston-service" in body
