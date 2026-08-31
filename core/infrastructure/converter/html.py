import codecs
import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from core.infrastructure.converter.utils import collapse_blank_lines, fenced_code_block

# Frequent Cyrillic bytes/letters used by the windows-1251 heuristic below.
_CYRILLIC_LETTERS_RE = re.compile(r"[\u0400-\u04FF]")
_COMMON_RUSSIAN_RE = re.compile(r"[оеаинтстрвл]", re.IGNORECASE)

# The characters cp1252 maps into 0x80-0x9F (smart quotes, dashes, euro) — the
# bytes that make an undeclared page recoverable as windows-1252.
_CP1252_HIGH_RE = re.compile(r"[€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ]")

# Whitespace class that deliberately excludes \xa0 so &nbsp; survives the
# inline whitespace collapse instead of degrading into a plain space.
_INLINE_WS_RE = re.compile(r"[ \t\n\r\f\v]+")

# Blockquote depth sentinels embedded in the output stream (never part of the
# source: NUL bytes are stripped from data before parsing).
_BQ_MARKER_RE = re.compile(r"\x00(\d+)\x00")


def _escape_title(title: str) -> str:
    """Escape a link/image title for use inside a double-quoted title."""
    return title.replace("\\", "\\\\").replace('"', '\\"')


def _escape_alt(alt: str) -> str:
    """Escape square brackets in image alt text so they cannot break the
    ![...](...) markup."""
    return alt.replace("[", "\\[").replace("]", "\\]")


def _clean_url(url: str) -> str:
    """Make a URL safe inside a Markdown inline link: spaces become %20 and
    unbalanced parentheses are escaped (balanced ones are valid as-is)."""
    url = url.replace(" ", "%20")
    if url.count("(") != url.count(")"):
        url = url.replace("(", "\\(").replace(")", "\\)")
    return url


def _decode_html_bytes(data: bytes) -> str:
    """Decode raw HTML bytes to text.

    Order: BOM → declared ``<meta charset>`` / XML ``encoding`` → strict UTF-8
    → windows-1251 heuristic → latin-1 (never fails). Pages without any
    declared charset in a non-UTF-8 encoding (common for legacy windows-1251
    content) are recovered instead of degrading to mojibake.
    """
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return data.decode("utf-32", errors="replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig", errors="replace")

    # The charset declaration lives in the document head; scan a generous
    # prefix. Search inside <meta> tags (and XML prologs) only, so the literal
    # word "charset" in body text cannot hijack decoding.
    head = data[:4096]
    match = re.search(rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_.\-]+)""", head, re.IGNORECASE)
    if not match:
        match = re.search(rb"""<\?xml[^>]+encoding\s*=\s*["']([^"']+)""", head, re.IGNORECASE)
    if match:
        declared = match.group(1).decode("ascii", "ignore")
        try:
            codecs.lookup(declared)
        except LookupError:
            declared = ""
        if declared:
            return data.decode(declared, errors="replace")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Undeclared legacy Cyrillic: dense 0xC0-0xFF bytes, almost no cp1252
    # smart-quote bytes, and the cp1251 decoding must look like Russian text
    # (top frequent letters dominate) before committing to it.
    size = len(data)
    if size:
        high = sum(1 for b in data if 0xC0 <= b <= 0xFF)
        smart = sum(1 for b in data if 0x91 <= b <= 0x94)
        if high / size >= 0.30 and smart / size <= 0.01:
            try:
                text = data.decode("cp1251")
            except UnicodeDecodeError:
                text = ""
            cyr = len(_CYRILLIC_LETTERS_RE.findall(text))
            if cyr >= 3:
                common = len(_COMMON_RUSSIAN_RE.findall(text))
                if common / cyr >= 0.35:
                    return text

    # Undeclared windows-1252: bytes in 0x80-0x9F (undefined as printable in
    # latin-1) decode to smart quotes/dashes; require strict decoding plus at
    # least one such character so ASCII pages keep the latin-1 fallback.
    if any(0x80 <= b <= 0x9F for b in data):
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            text = ""
        if text and _CP1252_HIGH_RE.search(text):
            return text

    return data.decode("latin-1", errors="replace")


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
        # Open list items as (continuation indent, content seen). Block tags
        # inside an item must not split the item from its list, so paragraph
        # breaks become indented continuation lines instead of "\n\n".
        self._li_stack: List[Tuple[str, bool]] = []
        # Blockquote nesting depth. Emitted as a sentinel token in the output
        # stream; get_markdown() prefixes every line in the region with "> ",
        # which also keeps fences/tables inside the quote.
        self._bq_depth = 0
        # Open inline emphasis markers ("**", "*", "~~", "`") so a stray end
        # tag (</b> without <b>) cannot leak raw markers into the output.
        self._inline_depth: Dict[str, int] = {}

    # --- inline marker helpers -------------------------------------------

    def _open_marker(self, token: str) -> None:
        self._inline_depth[token] = self._inline_depth.get(token, 0) + 1
        self._append_token(token)

    def _close_marker(self, token: str) -> None:
        """Emit the closing marker only when a matching tag is open."""
        if self._inline_depth.get(token, 0) > 0:
            self._inline_depth[token] -= 1
            self._append_token(token)

    # --- block-context helpers -------------------------------------------

    def _line_has_content(self) -> bool:
        """True when the current output line already carries visible content
        (blockquote sentinels don't count)."""
        if not self._output:
            return False
        tail = self._output[-1].rsplit("\n", 1)[-1]
        return bool(_BQ_MARKER_RE.sub("", tail))

    def _li_block_break(self, blank: bool) -> None:
        """Block boundary inside a list item: emit an indented continuation
        line (optionally with a blank line before it) instead of a paragraph
        break at column 0, which would split the item from the list."""
        if not self._li_stack:
            return
        indent, seen = self._li_stack[-1]
        if not seen:
            # Item content has not started; keep the marker line clean.
            return
        self._ensure_newline(1)
        if blank:
            self._append_token("\n" + indent)
        else:
            self._append_token(indent)

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
            if self._li_stack:
                # A fenced block inside a list item: continuation lines are
                # indented so the fence stays part of the item.
                indent, seen = self._li_stack[-1]
                self._li_stack[-1] = (indent, True)
                if seen:
                    self._ensure_newline(1)
                    self._append_token("\n" + indent)
                else:
                    self._append_token(indent)
            else:
                self._ensure_newline(2)
            return

        if self._in_pre:
            # Inside <pre> everything is verbatim code content: no block or
            # inline handling may emit outside the fenced buffer.
            if tag_lower == "br" and self._pre_buffer is not None:
                self._pre_buffer.append("\n")
            return

        if tag_lower == "code":
            self._open_marker("`")
            return

        if tag_lower in ("b", "strong"):
            self._open_marker("**")
            return

        if tag_lower in ("i", "em"):
            self._open_marker("*")
            return

        if tag_lower in ("s", "strike", "del"):
            self._open_marker("~~")
            return

        if tag_lower == "blockquote":
            if self._current_cell is None and self._current_link is None and not self._in_table and not self._li_stack:
                self._bq_depth += 1
                if self._line_has_content():
                    self._ensure_newline(2)
                self._output.append(f"\x00{self._bq_depth}\x00")
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._current_cell is not None:
                # Headings are invalid inside pipe-table cells; keep only the
                # text (the closing tag adds a separator) so no '#' leaks out.
                return
            if self._li_stack:
                # Headings are invalid inside list items; keep only the text
                # as a new paragraph of the item.
                self._li_block_break(True)
                return
            self._ensure_newline(2)
            self._saw_heading = True
            self._output.append("#" * int(tag_lower[1]) + " ")
            return

        if tag_lower == "hr":
            if self._current_cell is None and self._current_link is None and not self._li_stack:
                self._ensure_newline(2)
                self._output.append("---\n\n")
            # hr inside a link/cell/list item: no meaningful inline equivalent, drop.
            return

        if tag_lower == "br":
            if self._in_table:
                if self._current_cell is not None:
                    self._current_cell.append(" ")
            elif self._li_stack:
                self._append_token("\n" + self._li_stack[-1][0])
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
            if self._current_cell is not None:
                # Lists inside table cells are flattened into the cell text;
                # no bullet markers may leak into the surrounding output.
                self._append_token(" ")
                return
            depth = len(self._list_stack) - 1
            indent = "  " * max(0, depth)
            self._ensure_newline(1)
            if self._list_stack:
                list_type, count = self._list_stack[-1]
                if list_type == "ol":
                    self._append_token(f"{indent}{count}. ")
                    self._list_stack[-1] = (list_type, count + 1)
                else:
                    self._append_token(f"{indent}- ")
            else:
                self._append_token("- ")
            # Continuation lines of this item are indented past its marker.
            self._li_stack.append(("  " * (max(0, depth) + 1), False))
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
            if self._current_link is not None:
                # Nested anchor: invalid HTML — keep the outer link, let the
                # inner text flow into it, and remember to skip its end tag.
                self._nested_link_depth += 1
                return
            href = _clean_url(attr_dict.get("href", "").strip())
            title = attr_dict.get("title", "").strip()
            if href.lower().startswith("javascript:"):
                href = ""
            self._current_link = (href, title, [])
            return

        if tag_lower == "img":
            src = _clean_url(attr_dict.get("src", "").strip())
            alt = _escape_alt(attr_dict.get("alt", "").strip() or "Image")
            title = attr_dict.get("title", "").strip()
            if src.startswith("data:"):
                src = "data:..."
            if src:
                title_suffix = f' "{_escape_title(title)}"' if title else ""
                # Route through _append_token so images inside links become
                # proper [![alt](src)](href) and images inside table cells
                # stay in their cell.
                self._append_token(f"![{alt}]({src}{title_suffix})")
            return

        if tag_lower in ("p", "div", "article", "section", "header", "dt", "dd"):
            if self._li_stack:
                self._li_block_break(tag_lower in ("p", "dt", "dd"))
            else:
                self._ensure_newline(2 if tag_lower in ("p", "dt", "dd") else 1)
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
            block = fenced_code_block(content) if content else "```\n```"
            if self._li_stack:
                indent = self._li_stack[-1][0]
                block = ("\n" + indent).join(block.split("\n"))
                # Trailing indent so inline content following the fence stays
                # inside the item (harmlessly rstripped if nothing follows).
                self._append_token(block + "\n" + indent)
                return
            self._append_token(block + "\n\n")
            return

        if self._in_pre:
            return

        if tag_lower == "code":
            self._close_marker("`")
            return

        if tag_lower in ("b", "strong"):
            self._close_marker("**")
            return

        if tag_lower in ("i", "em"):
            self._close_marker("*")
            return

        if tag_lower in ("s", "strike", "del"):
            self._close_marker("~~")
            return

        if tag_lower == "blockquote":
            if self._current_cell is not None:
                self._append_token(" ")
            elif self._li_stack:
                pass
            elif self._bq_depth > 0 and not self._in_table:
                self._bq_depth -= 1
                self._output.append(f"\x00{self._bq_depth}\x00")
                if self._line_has_content():
                    self._ensure_newline(2)
            else:
                self._ensure_newline(2)
            return

        if tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._current_cell is not None:
                self._append_token(" ")
            elif self._li_stack:
                pass
            else:
                self._ensure_newline(2)
            return

        if tag_lower in ("p", "dt", "dd"):
            if self._current_cell is not None:
                self._append_token(" ")
            elif self._li_stack:
                pass
            else:
                self._ensure_newline(2)
            return

        if tag_lower in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._ensure_newline(1)
            if self._li_stack:
                # Keep any trailing item content indented under the item.
                self._append_token(self._li_stack[-1][0])
            return

        if tag_lower == "li":
            if self._li_stack:
                self._li_stack.pop()
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
                        # Separate the table from any text that leaked between
                        # the rows (e.g. <caption> content), so the first pipe
                        # row starts on its own line.
                        self._ensure_newline(2)
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
                text = re.sub(r"\s+", " ", "".join(text_parts)).strip()
                if not text:
                    text = href
                # Detach the link state first so _append_token routes the
                # rendered markdown into the enclosing cell/output, not back
                # into the link text itself (e.g. links inside table cells).
                self._current_link = None
                self._nested_link_depth = 0
                if href and text:
                    title_suffix = f' "{_escape_title(title)}"' if title else ""
                    self._append_token(f"[{text}]({href}{title_suffix})")
                elif text:
                    self._append_token(text)
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

        # Link first (mirrors _append_token): text of a link inside a table
        # cell belongs to the link text, not straight into the cell.
        if self._current_link is not None:
            self._current_link[2].append(data)
            return

        if self._in_table and self._current_cell is not None:
            self._current_cell.append(data)
            return

        cleaned = _INLINE_WS_RE.sub(" ", data.replace("\x00", ""))
        if cleaned.strip() and self._li_stack:
            # Mark the open list item as having received content, so later
            # block tags inside it produce continuation lines.
            self._li_stack[-1] = (self._li_stack[-1][0], True)
        self._append_token(cleaned)

    def unknown_decl(self, content: str) -> None:
        """Recover CDATA section content (``<![CDATA[...]]>``), which
        ``HTMLParser`` reports as an unknown declaration rather than data."""
        if content.startswith("CDATA["):
            self.handle_data(content[len("CDATA[") :])

    def _ensure_newline(self, count: int = 1) -> None:
        if self._in_table or self._current_link is not None or self._in_pre:
            # Layout newlines are meaningless while a table, a link, or a
            # pre-buffer owns the sink: block tags inside them are flattened
            # into cell/link text, so they must not leak stray newlines into
            # the main output.
            return
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
        # Auto-close any inline markers whose tags were never closed, so a
        # dangling "<b>" still renders instead of leaking a bare "**".
        for token in ("**", "*", "~~", "`"):
            depth = self._inline_depth.get(token, 0)
            if depth > 0:
                raw_text = raw_text.rstrip("\n") + token * depth
        lines = [line.rstrip() for line in raw_text.splitlines()]
        cleaned = "\n".join(lines).strip()

        # Re-apply blockquote prefixes from the depth sentinels: every line
        # between an opening and closing sentinel is prefixed with the quote's
        # depth of "> ". This keeps fences, tables, and lists intact inside
        # the quote (unlike emitting "> " inline at start-tag time).
        if _BQ_MARKER_RE.search(cleaned):
            cleaned = self._apply_blockquote_markers(cleaned)

        cleaned = collapse_blank_lines(cleaned)
        # Emit the document <title> as a heading only when the body provides
        # no heading of its own, to avoid duplicated headings.
        title = " ".join((self._title or "").split())
        if title and not self._saw_heading:
            cleaned = f"# {title}\n\n{cleaned}" if cleaned else f"# {title}"
        return cleaned

    @staticmethod
    def _apply_blockquote_markers(text: str) -> str:
        """Prefix lines between blockquote depth sentinels with "> " markers.

        Sentinels may sit mid-line (right after content on close, right
        before content on open), so each line is split on them and every
        fragment is prefixed with the depth in effect at its position.
        Blank lines are left untouched: a blank line does not end a quote
        in Markdown, and the next prefixed line resumes it.
        """
        out: List[str] = []
        depth = 0
        for line in text.split("\n"):
            parts = _BQ_MARKER_RE.split(line)
            if len(parts) == 1:
                # Marker-less line: prefix with the depth in effect.
                out.append(("> " * depth) + line if depth else line)
                continue
            seg_depth = depth
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    depth = int(part)
                    seg_depth = depth
                elif part:
                    out.append(("> " * seg_depth) + part if seg_depth else part)
        return "\n".join(out)


def html_to_markdown(html_content: str | bytes) -> str:
    """Convert HTML string or bytes to clean Markdown."""
    if isinstance(html_content, bytes):
        html_content = _decode_html_bytes(html_content)

    parser = HTMLToMarkdownParser()
    parser.feed(html_content)
    parser.close()
    return parser.get_markdown()
