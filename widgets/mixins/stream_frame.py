from widgets.utils.row_format import compose_rows

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Both footers render with 1 cell of horizontal padding on each side.
FOOTER_GUTTER = 2


class StreamFrameMixin:
    """Shared animated-frame redraw for status footers.

    ``_render_stream_frame`` redraws only the spinner frame from cached grid
    rows (no git/table rebuild) on each tick; ``_swap_frame`` swaps the old
    spinner char in the first row. Used by both ``StatusFooter`` (1- or
    2-column cached rows) and ``SubagentStatusFooter`` (2-column rows).

    Rows are laid out as fitted ``Text`` lines (see
    :func:`widgets.utils.row_format.compose_rows`) so a long left cell
    degrades with an ellipsis instead of being clipped by the fixed footer
    height.
    """

    def row_width(self) -> int:
        """Usable cell width for footer rows (terminal width minus gutter)."""
        from widgets.utils.responsive import resolve_width

        return max(10, resolve_width(self) - FOOTER_GUTTER)

    def compose_footer_rows(self, rows) -> None:
        """Render ``rows`` (1- or 2-tuples of markup) into the footer widget."""
        self._last_grid_rows = list(rows)
        self.update(compose_rows([tuple(row) for row in rows], self.row_width()))

    def _render_stream_frame(self) -> None:
        """Redraw only the animated frame from cached status rows (no git/rebuild)."""
        if not self.is_generating:
            return
        rows = getattr(self, "_last_grid_rows", None)
        if rows is None:
            return
        try:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            redrawn = []
            for i, row in enumerate(rows):
                left = row[0]
                if i == 0:
                    left = self._swap_frame(left, frame)
                redrawn.append((left, row[1]) if len(row) > 1 else (left,))
            self.update(compose_rows(redrawn, self.row_width()))
        except Exception:
            pass

    @staticmethod
    def _swap_frame(left: str, frame: str) -> str:
        """Replace the old spinner char in the cached left cell with the new frame."""
        try:
            idx = left.index("]") + 1
            return left[:idx] + frame + left[idx + 1 :]
        except Exception:
            return left
