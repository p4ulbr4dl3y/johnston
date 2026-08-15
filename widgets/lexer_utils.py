import os
import re
from typing import Any
from urllib.parse import urlparse

import pygments
from rich.text import Text

from widgets.presentation.widgets.chat_markdown import TOKEN_COLORS

HUNK_HEADER_RE = re.compile(
    r"^@@\s+-\s*(\d+)(?:,\s*(\d+))?\s+\+\s*(\d+)(?:,\s*(\d+))?\s+@@"
)

EXTENSION_MAPPING = {
    "py": "python",
    "js": "javascript",
    "jsx": "jsx",
    "ts": "typescript",
    "tsx": "tsx",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "md": "markdown",
    "sh": "bash",
    "bash": "bash",
    "zsh": "bash",
    "rs": "rust",
    "go": "go",
    "c": "c",
    "cpp": "cpp",
    "h": "c",
    "hpp": "cpp",
    "sql": "sql",
    "toml": "toml",
    "ini": "ini",
    "dockerfile": "dockerfile",
    "xml": "xml",
}


def guess_lexer_name(path_str: str) -> str:
    if not path_str:
        return "text"
    clean_path = urlparse(path_str).path if path_str.startswith(("http://", "https://")) else path_str
    ext = os.path.splitext(clean_path)[1].lower().lstrip(".")
    return EXTENSION_MAPPING.get(ext, ext or "text")


def lex_block_to_line_texts(
    code_lines: list[str],
    lexer: Any,
    token_colors: dict = TOKEN_COLORS,
    lex_fn: Any = pygments.lex,
) -> list[Text]:
    if not code_lines:
        return []
    if not lexer:
        return [Text(line) for line in code_lines]

    if hasattr(lexer, "stripnl"):
        lexer.stripnl = False
    if hasattr(lexer, "stripall"):
        lexer.stripall = False
    if hasattr(lexer, "ensurenl"):
        lexer.ensurenl = False

    # Normalize code_lines so elements with embedded newlines do not collide:
    # an embedded "\n" inside a single element would otherwise be split by the
    # lexer into extra lines that get sliced away below, silently losing content.
    expanded: list[str] = []
    for line in code_lines:
        expanded.extend(line.split("\n"))
    code_lines = expanded

    full_code = "\n".join(code_lines)
    try:
        tokens = lex_fn(full_code, lexer)
        line_texts = [Text()]
        for tok_type, val in tokens:
            parts = val.split("\n")
            for idx, part in enumerate(parts):
                if idx > 0:
                    line_texts.append(Text())
                if part:
                    style = None
                    curr = tok_type
                    while curr:
                        if curr in token_colors:
                            style = token_colors[curr]
                            break
                        curr = curr.parent
                    line_texts[-1].append(part, style=style)

        while len(line_texts) < len(code_lines):
            line_texts.append(Text())
        return line_texts[: len(code_lines)]
    except Exception:
        return [Text(line) for line in code_lines]


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
    """Generates unified diff text from tool arguments via the registry alias resolver."""
    if not isinstance(args, dict):
        return ""
    from tools.registry import normalize_tool_args

    norm = normalize_tool_args(tool_name, args)

    chunks = norm.get("edits")
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
        old_s = norm.get("old_str", "")
        new_s = norm.get("new_str", "")
        start_l = norm.get("start_line") or 1
        if old_s or new_s:
            diff_parts.extend(generate_chunk_unified_diff(old_s, new_s, file_path, start_l))

    return "\n".join(diff_parts) if diff_parts else ""
