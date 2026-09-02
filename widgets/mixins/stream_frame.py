from rich.table import Table

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class StreamFrameMixin:
    """Shared animated-frame redraw for status footers.

    ``_render_stream_frame`` redraws only the spinner frame from cached grid
    rows (no git/table rebuild) on each tick; ``_swap_frame`` swaps the old
    spinner char in the first row. Used by both ``StatusFooter`` (1- or
    2-column cached rows) and ``SubagentStatusFooter`` (2-column rows).
    """

    def _render_stream_frame(self) -> None:
        """Redraw only the animated frame from cached status rows (no git/rebuild)."""
        if not self.is_generating:
            return
        rows = getattr(self, "_last_grid_rows", None)
        if rows is None:
            return
        try:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            grid = Table.grid(expand=True)
            if rows and len(rows[0]) == 1:
                grid.add_column(justify="left")
                for i, row in enumerate(rows):
                    cell = row[0]
                    if i == 0:
                        cell = self._swap_frame(cell, frame)
                    grid.add_row(cell)
            else:
                grid.add_column(justify="left")
                grid.add_column(justify="right")
                for i, (left, right) in enumerate(rows):
                    if i == 0:
                        left = self._swap_frame(left, frame)
                    grid.add_row(left, right)
            self.update(grid)
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
