"""Shared Markdown table rendering for the document converter package."""

from typing import List


def render_markdown_table(rows: List[List[str]]) -> str:
    """Render a list of row cell-strings into a Markdown pipe table.

    The first row becomes the header; shorter rows are padded with empty
    cells to the widest row so columns stay aligned. Returns ``""`` when there
    are no rows or the table has zero columns.
    """
    if not rows:
        return ""

    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return ""

    normalized = [r + [""] * (col_count - len(r)) for r in rows]
    header = normalized[0]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * col_count) + " |"]

    for row in normalized[1:]:
        out.append("| " + " | ".join(row) + " |")

    return "\n".join(out)
