from rich.table import Table

SPINNER_FRAMES = ["◐", "◓", "◑", "◒"]


class StreamFrameMixin:
    """Shared animated-frame redraw for status footers.

    ``_render_stream_frame`` redraws only the spinner frame from cached grid
    rows (no git/table rebuild) on each tick; ``_swap_frame`` swaps the old
    spinner char in the target row. Used by both ``StatusFooter`` (target row 0)
    and ``SubagentStatusFooter`` (target row -1).
    """

    def _render_stream_frame(self) -> None:
        """Redraw only the animated frame from cached status rows (no git/rebuild)."""
        if not getattr(self, "is_generating", False):
            return
        rows = getattr(self, "_last_grid_rows", None)
        if not rows:
            return
        try:
            target_row = getattr(self, "_stream_frame_row_index", 0)
            if target_row < 0:
                target_row = len(rows) + target_row

            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            grid = Table.grid(expand=True)
            if len(rows[0]) == 1:
                grid.add_column(justify="left")
                for i, row in enumerate(rows):
                    cell = row[0]
                    if i == target_row:
                        cell = self._swap_frame(cell, frame)
                    grid.add_row(cell)
            else:
                grid.add_column(justify="left")
                grid.add_column(justify="right")
                for i, (left, right) in enumerate(rows):
                    if i == target_row:
                        left = self._swap_frame(left, frame)
                    grid.add_row(left, right)
            self.update(grid)
        except Exception:
            pass

    @staticmethod
    def _swap_frame(left: str, frame: str) -> str:
        """Replace the old spinner char in the cached left cell with the new frame."""
        for f in SPINNER_FRAMES:
            if f in left:
                return left.replace(f, frame, 1)
        return left

