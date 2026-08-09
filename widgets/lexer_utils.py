import os
from typing import Any
from urllib.parse import urlparse

import pygments
from rich.text import Text

from widgets.chat_markdown import TOKEN_COLORS

EXTENSION_MAPPING = {
    "py": "python", "js": "javascript", "jsx": "jsx", "ts": "typescript", "tsx": "tsx",
    "html": "html", "css": "css", "scss": "scss", "json": "json", "yaml": "yaml",
    "yml": "yaml", "md": "markdown", "sh": "bash", "bash": "bash", "zsh": "bash",
    "rs": "rust", "go": "go", "c": "c", "cpp": "cpp", "h": "c", "hpp": "cpp",
    "sql": "sql", "toml": "toml", "ini": "ini", "dockerfile": "dockerfile", "xml": "xml"
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
        return line_texts[:len(code_lines)]
    except Exception:
        return [Text(line) for line in code_lines]


def generate_chunk_unified_diff(
    old_content: str,
    new_content: str,
    file_path: str = "file",
    start_line: int = 1,
) -> list[str]:
    """Generates unified diff lines for a single chunk, adjusting @@ line numbers."""
    import difflib
    import re

    if not old_content and not new_content:
        return []

    d_lines = list(difflib.unified_diff(
        old_content.splitlines(),
        new_content.splitlines(),
        fromfile=file_path or "file",
        tofile=file_path or "file",
        lineterm="",
    ))
    if d_lines and len(d_lines) > 2 and d_lines[2].startswith("@@"):
        h_m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", d_lines[2])
        if h_m:
            old_cnt = h_m.group(2) or "1"
            new_cnt = h_m.group(4) or "1"
            d_lines[2] = f"@@ -{start_line},{old_cnt} +{start_line},{new_cnt} @@"
    return d_lines


def build_edit_diff_text(args: dict, file_path: str = "file") -> str:
    """Generates unified diff text from tool arguments (supporting replacement_chunks and single old/new strings)."""
    if not isinstance(args, dict):
        return ""

    chunks = args.get("ReplacementChunks") or args.get("replacement_chunks") or args.get("edits")
    diff_parts = []
    if chunks and isinstance(chunks, list):
        for chunk in chunks:
            if isinstance(chunk, dict):
                old_c = chunk.get("TargetContent") or chunk.get("target_content") or chunk.get("old_string") or chunk.get("old_str") or ""
                new_c = chunk.get("ReplacementContent") or chunk.get("replacement_content") or chunk.get("new_string") or chunk.get("new_str") or ""
                start_l = chunk.get("StartLine") or chunk.get("start_line") or 1
                if old_c or new_c:
                    diff_parts.extend(generate_chunk_unified_diff(old_c, new_c, file_path, start_l))
    else:
        old_s = args.get("old_string") or args.get("old_str") or args.get("target_content") or args.get("TargetContent") or ""
        new_s = args.get("new_string") or args.get("new_str") or args.get("replacement_content") or args.get("ReplacementContent") or ""
        start_l = args.get("StartLine") or args.get("start_line") or 1
        if old_s or new_s:
            diff_parts.extend(generate_chunk_unified_diff(old_s, new_s, file_path, start_l))

    return "\n".join(diff_parts) if diff_parts else ""

