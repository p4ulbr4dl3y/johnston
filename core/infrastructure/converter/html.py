import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple

from core.infrastructure.converter.utils import collapse_blank_lines, fenced_code_block


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
        "nav",
        "footer",
        "aside",
        "iframe",
    }

    VOID_TAGS = {
        "meta",
        "link",
        "img",
        "br",
        "hr",
        "input",
        "area",
        "base",
        "col",
        "embed",
        "param",
        "source",
        "track",
        "wbr",
    }

    BLOCK_TAGS = {
        "p",
        "div",
        "article",
        "section",
        "header",
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
        self._pre_buffer: Optional[List[str]] = None  # buffered until </pre> to size the fence
        self._in_code = False
        self._table_rows: List[List[str]] = []
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[List[str]] = None
        self._in_table = False
        # Enclosing table state pushed aside while a nested table is parsed.
        self._table_stack: List[Tuple[Optional[List[str]], Optional[List[str]], List[List[str]]]] = []
        self._current_link: Optional[Tuple[str, str, List[str]]] = None  # (href, title, text_parts)
        self._nested_link_depth = 0
        self._title: Optional[str] = None
        self._in_title = False
        self._saw_heading = False

    def _append_token(self, token: str) -> None:
        if self._current_link is not None:
            self._current_link[2].append(token)
        elif self._current_cell is not None:
            self._current_cell.append(token)
        else:
            self._output.append(token)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag_lower in self.VOID_TAGS:
            if tag_lower in ("meta", "link", "base", "input", "param", "track", "wbr"):
                return

        if tag_lower == "title":
            # <title> lives inside <head>, which is otherwise ignored — handle
            # it before the ignore-depth gate so the document title is captured.
            if not self._in_title:
                self._in_title = True
            return

        if tag_lower in self.IGNORE_TAGS:
            self._ignore_stack_depth += 1
            return

        if self._ignore_stack_depth > 0:
            return

        if tag_lower == "pre":
            self._in_pre = True
            self._pre_buffer = []
            self._ensure_newline(2)
            return

        if tag_lower == "code":
            if not self._in_pre:
                self._in_code = True
                self._append_token("`")
            return

        if tag_lower in ("b", "strong"):
            self._append_token("**")
            return

        if tag_lower in ("i", "em"):
            self._append_token("*")
            return

        if tag_lower in ("s", "strike", "del"):
            self._append_token("~~")
            return

        if tag_lower == "blockquote":
            self._ensure_newline(2)
            self._output.append("> ")
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_lower[1])
            self._ensure_newline(2)
            self._saw_heading = True
            self._output.append("#" * level + " ")
            return

        if tag_lower == "hr":
            self._ensure_newline(2)
            self._output.append("---\n\n")
            return

        if tag_lower == "br":
            if self._in_pre:
                if self._pre_buffer is not None:
                    self._pre_buffer.append("\n")
                else:
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
            if self._in_table:
                # Nested table: pause the enclosing table's state; the rendered
                # inner table will be spliced into the enclosing cell text.
                self._table_stack.append((self._current_row, self._current_cell, self._table_rows))
                self._table_rows = []
                self._current_row = None
                self._current_cell = None
            else:
                self._in_table = True
                self._table_rows = []
                self._ensure_newline(2)
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
            if self._current_link is not None:
                # Nested anchor: invalid HTML — keep the outer link, let the
                # inner text flow into it, and remember to skip its end tag.
                self._nested_link_depth += 1
                return
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
                # Route through _append_token so images inside links become
                # proper [![alt](src)](href) and images inside table cells
                # stay in their cell.
                self._append_token(f"![{alt}]({src}{title_suffix})")
            return

        if tag_lower in ("p", "div", "article", "section", "header"):
            self._ensure_newline(2 if tag_lower == "p" else 1)
            return

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower in self.VOID_TAGS:
            return

        if tag_lower == "title":
            self._in_title = False
            return

        if tag_lower in self.IGNORE_TAGS:
            if self._ignore_stack_depth > 0:
                self._ignore_stack_depth -= 1
            return

        if self._ignore_stack_depth > 0:
            return

        if tag_lower == "pre":
            self._in_pre = False
            # fenced_code_block adds the newline before the closing fence itself,
            # so strip trailing newlines from the buffered content.
            content = "".join(self._pre_buffer or []).rstrip("\n")
            self._pre_buffer = None
            if content:
                self._output.append(fenced_code_block(content) + "\n\n")
            else:
                self._output.append("```\n```\n\n")
            return

        if tag_lower == "code":
            if not self._in_pre:
                self._in_code = False
                self._append_token("`")
            return

        if tag_lower in ("b", "strong"):
            self._append_token("**")
            return

        if tag_lower in ("i", "em"):
            self._append_token("*")
            return

        if tag_lower in ("s", "strike", "del"):
            self._append_token("~~")
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
                inner_md = self._build_table(self._table_rows)
                self._table_rows = []
                if self._table_stack:
                    # Restore the enclosing table and splice the rendered inner
                    # table into its cell as flattened text (GFM cannot nest
                    # pipe tables; pipes are escaped when the cell closes).
                    self._current_row, self._current_cell, self._table_rows = self._table_stack.pop()
                    if self._current_cell is not None and inner_md:
                        flat = inner_md.replace("\n", " ").strip()
                        if flat:
                            self._current_cell.append(f" {flat} ")
                else:
                    self._in_table = False
                    if inner_md:
                        self._output.append(inner_md + "\n\n")
                    self._ensure_newline(2)
            return

        if tag_lower == "a":
            if self._nested_link_depth > 0:
                # This closes a nested anchor we ignored — the outer link stays open.
                self._nested_link_depth -= 1
                return
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
                self._nested_link_depth = 0
            return

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title = (self._title or "") + data
            return

        if self._ignore_stack_depth > 0:
            return

        if self._in_pre:
            if self._pre_buffer is not None:
                self._pre_buffer.append(data)
            else:
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

    def _build_table(self, rows: List[List[str]]) -> str:
        """Render collected rows as a GFM pipe table (without trailing blank line)."""
        if not rows:
            return ""

        col_count = max(len(row) for row in rows)
        if col_count == 0:
            return ""

        normalized_rows = []
        for row in rows:
            padded = row + [""] * (col_count - len(row))
            normalized_rows.append(padded)

        header = normalized_rows[0]
        lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * col_count) + " |"]
        for row in normalized_rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def get_markdown(self) -> str:
        raw_text = "".join(self._output)
        lines = [line.rstrip() for line in raw_text.splitlines()]
        cleaned = "\n".join(lines).strip()
        cleaned = collapse_blank_lines(cleaned)
        # Emit the document <title> as a heading only when the body provides
        # no heading of its own, to avoid duplicated headings.
        title = " ".join((self._title or "").split())
        if title and not self._saw_heading:
            cleaned = f"# {title}\n\n{cleaned}" if cleaned else f"# {title}"
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
