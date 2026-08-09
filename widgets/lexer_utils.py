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
