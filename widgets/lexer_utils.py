"""Re-export stub keeping historical import paths.

Pure presentation helpers live in :mod:`widgets.utils.lexer`; the edit diff
builders ``generate_chunk_unified_diff`` / ``build_edit_diff_text`` are kept
here because they drag in ``core``/``tools`` (forbidden in ``widgets/utils/``).
"""
import pygments  # noqa: F401  (kept so `widgets.lexer_utils.pygments` resolves for patching)

from widgets.utils.lexer import (  # noqa: F401
    EXTENSION_MAPPING,
    HUNK_HEADER_RE,
    guess_lexer_name,
    lex_block_to_line_texts,
)


def generate_chunk_unified_diff(
    old_content: str,
    new_content: str,
    file_path: str = "file",
    start_line: int = 1,
) -> list[str]:
    """Generates unified diff lines for a single chunk, adjusting @@ line numbers.

    Uses git's patience diff when available, falling back to difflib.
    """

    if not old_content and not new_content:
        return []

    from core.infrastructure.runtime.git_utils import make_git_diff

    diff_text = make_git_diff(
        old_content,
        new_content,
        fromfile=file_path or "file",
        tofile=file_path or "file",
    )
    # Drop the `diff --git` / `index` metadata lines git adds, keep hunk/body.
    d_lines = [
        line
        for line in (diff_text.splitlines() if diff_text else [])
        if not line.startswith(("diff --git ", "index "))
    ]

    for i, line in enumerate(d_lines):
        if line.startswith("@@"):
            h_m = HUNK_HEADER_RE.match(line)
            if h_m:
                old_cnt = h_m.group(2) or "1"
                new_cnt = h_m.group(4) or "1"
                d_lines[i] = f"@@ -{start_line},{old_cnt} +{start_line},{new_cnt} @@"
            break
    return d_lines


def build_edit_diff_text(args: dict, file_path: str = "file", tool_name: str = "edit") -> str:
    """Generates unified diff text from tool arguments."""
    if not isinstance(args, dict):
        return ""
    chunks = args.get("edits")
    diff_parts = []
    if chunks and isinstance(chunks, list):
        for chunk in chunks:
            if isinstance(chunk, dict):
                old_c = chunk.get("old_str", "")
                new_c = chunk.get("new_str", "")
                start_l = chunk.get("start_line") or 1
                if old_c or new_c:
                    diff_parts.extend(generate_chunk_unified_diff(old_c, new_c, file_path, start_l))
    else:
        old_s = args.get("old_str", "")
        new_s = args.get("new_str", "")
        start_l = args.get("start_line") or 1
        if old_s or new_s:
            diff_parts.extend(generate_chunk_unified_diff(old_s, new_s, file_path, start_l))

    return "\n".join(diff_parts) if diff_parts else ""
