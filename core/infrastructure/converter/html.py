import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple


class HTMLToMarkdownParser(HTMLParser):
    """
    Converts HTML documents to clean GitHub-flavored Markdown using Python stdlib html.parser.
    Strips noise (scripts, styles, navigation) and formats headings, lists, tables, links, and code blocks.
    """

    IGNORE_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "head",
        "meta",
        "link",
        "nav",
        "footer",
        "header",
        "aside",
        "iframe",
    }

    BLOCK_TAGS = {
        "p",
        "div",
        "article",
        "section",
        "main",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "pre",
        "hr",
    }

    def __init__(self) -> None:
        super().__init__()
        self._output: List[str] = []
        self._tag_stack: List[str] = []
        self._ignore_stack_depth = 0
        self._list_stack: List[Tuple[str, int]] = []  # ('ul' | 'ol', current_count)
        self._in_pre = False
        self._in_code = False
        self._table_rows: List[List[str]] = []
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[List[str]] = None
        self._in_table = False
        self._current_link: Optional[Tuple[str, str, List[str]]] = None  # (href, title, text_parts)
        self._title: Optional[str] = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag_lower in self.IGNORE_TAGS:
            self._ignore_stack_depth += 1
            return

        if self._ignore_stack_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = True
            return

        if tag_lower == "pre":
            self._in_pre = True
            self._ensure_newline(2)
            self._output.append("```\n")
            return

        if tag_lower == "code":
            if not self._in_pre:
                self._in_code = True
                self._output.append("`")
            return

        if tag_lower in ("b", "strong"):
            self._output.append("**")
            return

        if tag_lower in ("i", "em"):
            self._output.append("*")
            return

        if tag_lower in ("s", "strike", "del"):
            self._output.append("~~")
            return

        if tag_lower == "blockquote":
            self._ensure_newline(2)
            self._output.append("> ")
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_lower[1])
            self._ensure_newline(2)
            self._output.append("#" * level + " ")
            return

        if tag_lower == "hr":
            self._ensure_newline(2)
            self._output.append("---\n\n")
            return

        if tag_lower == "br":
            if self._in_pre:
                self._output.append("\n")
            elif self._in_table:
                if self._current_cell is not None:
                    self._current_cell.append(" ")
            else:
                self._output.append("\n")
            return

        if tag_lower == "ul":
            self._ensure_newline(1)
            self._list_stack.append(("ul", 0))
            return

        if tag_lower == "ol":
            self._ensure_newline(1)
            start = 1
            if "start" in attr_dict:
                try:
                    start = int(attr_dict["start"])
                except ValueError:
                    start = 1
            self._list_stack.append(("ol", start))
            return

        if tag_lower == "li":
            self._ensure_newline(1)
            depth = len(self._list_stack) - 1
            indent = "  " * max(0, depth)
            if self._list_stack:
                list_type, count = self._list_stack[-1]
                if list_type == "ol":
                    self._output.append(f"{indent}{count}. ")
                    self._list_stack[-1] = (list_type, count + 1)
                else:
                    self._output.append(f"{indent}- ")
            else:
                self._output.append("- ")
            return

        if tag_lower == "table":
            self._ensure_newline(2)
            self._in_table = True
            self._table_rows = []
            return

        if tag_lower == "tr":
            if self._in_table:
                self._current_row = []
            return

        if tag_lower in ("th", "td"):
            if self._in_table and self._current_row is not None:
                self._current_cell = []
            return

        if tag_lower == "a":
            href = attr_dict.get("href", "").strip()
            title = attr_dict.get("title", "").strip()
            if href.lower().startswith("javascript:"):
                href = ""
            self._current_link = (href, title, [])
            return

        if tag_lower == "img":
            src = attr_dict.get("src", "").strip()
            alt = attr_dict.get("alt", "").strip() or "Image"
            title = attr_dict.get("title", "").strip()
            if src.startswith("data:"):
                src = "data:..."
            if src:
                title_suffix = f' "{title}"' if title else ""
                self._output.append(f"![{alt}]({src}{title_suffix})")
            return

        if tag_lower in ("p", "div", "article", "section"):
            self._ensure_newline(2 if tag_lower == "p" else 1)
            return

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in self.IGNORE_TAGS:
            if self._ignore_stack_depth > 0:
                self._ignore_stack_depth -= 1
            return

        if self._ignore_stack_depth > 0:
            return

        if tag_lower == "title":
            self._in_title = False
            return

        if tag_lower == "pre":
            self._in_pre = False
            self._ensure_newline(1)
            self._output.append("```\n\n")
            return

        if tag_lower == "code":
            if not self._in_pre:
                self._in_code = False
                self._output.append("`")
            return

        if tag_lower in ("b", "strong"):
            self._output.append("**")
            return

        if tag_lower in ("i", "em"):
            self._output.append("*")
            return

        if tag_lower in ("s", "strike", "del"):
            self._output.append("~~")
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._ensure_newline(2)
            return

        if tag_lower in ("p", "blockquote"):
            self._ensure_newline(2)
            return

        if tag_lower in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._ensure_newline(1)
            return

        if tag_lower == "li":
            self._ensure_newline(1)
            return

        if tag_lower in ("th", "td"):
            if self._in_table and self._current_cell is not None:
                cell_text = "".join(self._current_cell).strip().replace("\n", " ").replace("|", "\\|")
                if self._current_row is not None:
                    self._current_row.append(cell_text)
                self._current_cell = None
            return

        if tag_lower == "tr":
            if self._in_table and self._current_row is not None:
                if self._current_row:
                    self._table_rows.append(self._current_row)
                self._current_row = None
            return

        if tag_lower == "table":
            if self._in_table:
                self._in_table = False
                self._render_table()
                self._table_rows = []
                self._ensure_newline(2)
            return

        if tag_lower == "a":
            if self._current_link is not None:
                href, title, text_parts = self._current_link
                text = "".join(text_parts).strip()
                if not text:
                    text = href
                if href and text:
                    title_suffix = f' "{title}"' if title else ""
                    self._output.append(f"[{text}]({href}{title_suffix})")
                elif text:
                    self._output.append(text)
                self._current_link = None
            return

    def handle_data(self, data: str) -> None:
        if self._ignore_stack_depth > 0:
            return

        if self._in_title:
            self._title = (self._title or "") + data
            return

        if self._in_pre:
            self._output.append(data)
            return

        if self._in_table and self._current_cell is not None:
            self._current_cell.append(data)
            return

        if self._current_link is not None:
            self._current_link[2].append(data)
            return

        cleaned = re.sub(r"\s+", " ", data)
        self._output.append(cleaned)

    def _ensure_newline(self, count: int = 1) -> None:
        if not self._output:
            return
        last_str = self._output[-1]
        trailing_newlines = len(last_str) - len(last_str.rstrip("\n"))
        needed = max(0, count - trailing_newlines)
        if needed > 0:
            self._output.append("\n" * needed)

    def _render_table(self) -> None:
        if not self._table_rows:
            return

        col_count = max(len(row) for row in self._table_rows)
        if col_count == 0:
            return

        normalized_rows = []
        for row in self._table_rows:
            padded = row + [""] * (col_count - len(row))
            normalized_rows.append(padded)

        header = normalized_rows[0]
        self._output.append("| " + " | ".join(header) + " |\n")
        self._output.append("| " + " | ".join(["---"] * col_count) + " |\n")

        for row in normalized_rows[1:]:
            self._output.append("| " + " | ".join(row) + " |\n")
        self._output.append("\n")

    def get_markdown(self) -> str:
        raw_text = "".join(self._output)
        lines = [line.rstrip() for line in raw_text.splitlines()]
        cleaned = "\n".join(lines).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned


def html_to_markdown(html_content: str | bytes) -> str:
    """Convert HTML string or bytes to clean Markdown."""
    if isinstance(html_content, bytes):
        try:
            html_content = html_content.decode("utf-8")
        except UnicodeDecodeError:
            html_content = html_content.decode("latin-1", errors="replace")

    parser = HTMLToMarkdownParser()
    parser.feed(html_content)
    parser.close()
    return parser.get_markdown()
