"""Edge-case tests for widgets/chat_markdown bounding iterators and related code.

Detectors for real bugs in empty-row table updates. Tests intentionally RED.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from rich.text import Text

from widgets.presentation.widgets.chat_markdown import CustomMarkdownTableContent


class TestCustomMarkdownTableContentEmptyRows(unittest.IsolatedAsyncioTestCase):
    def _make_content(self, headers, rows, last_row=0):
        content = CustomMarkdownTableContent.__new__(CustomMarkdownTableContent)
        content.headers = headers
        content.rows = rows
        content.last_row = last_row
        content.styles = MagicMock()
        return content

    async def test_update_rows_with_empty_payload_sets_last_row(self):
        """Updating a table to zero rows must not crash (bounded enumerate leaves
        `row_index` undefined) and must leave last_row pointing at the previous row."""
        content = self._make_content([Text("h1")], [[Text("a")], [Text("b")]], last_row=2)
        content.query_children = MagicMock(return_value=MagicMock(remove=AsyncMock()))
        content.mount_all = AsyncMock()

        await content._update_rows([])

        self.assertEqual(content.last_row, 2)
        # No new cells should have been mounted.
        content.mount_all.assert_awaited_once_with([])


if __name__ == "__main__":
    unittest.main()
