import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple, Union

from core.infrastructure.converter.utils import clean_url, safe_read_zip_member

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Paragraph/block wrappers whose descendants hold real content: content
# controls (w:sdt), smart tags and tracked-change insertions.
_INLINE_WRAPPERS = {"ins", "smartTag", "moveTo"}
_BLOCK_WRAPPERS = {"sdt"}


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _iter_blocks(elem: ET.Element) -> Iterator[ET.Element]:
    """Yield block-level w:p / w:tbl elements.

    Descends into w:sdt content controls, which commonly wrap whole
    paragraphs or tables (Word cover pages, TOCs, templates) — without this
    their content is silently dropped.
    """
    for child in elem:
        tag = _local_tag(child)
        if tag in ("p", "tbl"):
            yield child
        elif tag in _BLOCK_WRAPPERS:
            content = None
            for sub in child.iter():
                if _local_tag(sub) == "sdtContent":
                    content = sub
                    break
            if content is not None:
                yield from _iter_blocks(content)


def _iter_inline(elem: ET.Element) -> Iterator[ET.Element]:
    """Yield inline w:r / w:hyperlink elements of a paragraph.

    Descends into tracked-change insertion containers (w:ins, w:moveTo) and
    smart tags so their runs are kept; w:del/w:moveFrom (deleted text) are
    skipped so the output matches the document with changes accepted.
    """
    for child in elem:
        tag = _local_tag(child)
        if tag in ("r", "hyperlink"):
            yield child
        elif tag in _INLINE_WRAPPERS:
            yield from _iter_inline(child)
        elif tag == "sdt":
            content = None
            for sub in child.iter():
                if _local_tag(sub) == "sdtContent":
                    content = sub
                    break
            if content is not None:
                yield from _iter_inline(content)


RunFormat = Tuple[bool, bool, bool]  # (bold, italic, strike)


def _wrap_inline(text: str, markers: str) -> str:
    """Wrap ``text`` in emphasis markers, moving edge whitespace outside.

    A closing delimiter preceded by whitespace does not close in CommonMark
    (e.g. ``**Bold1 **`` renders literally), so trailing/leading whitespace
    must sit outside the markers.
    """
    lead = text[: len(text) - len(text.lstrip())]
    core = text[len(lead) :]
    trail = core[len(core.rstrip()) :]
    core = core[: len(core) - len(trail)]
    if not core:
        return text
    return f"{lead}{markers}{core}{markers}{trail}"


def _render_runs(runs: List[Tuple[str, RunFormat]]) -> str:
    """Merge adjacent runs with identical formatting, then apply emphasis.

    Word splits text into many runs (spell check, rsids); wrapping each run
    separately produces ``**Bold1 ****Bold2**`` which most parsers refuse to
    render. Merging first yields a single ``**Bold1 Bold2**``.
    """
    merged: List[List] = []
    for text, fmt in runs:
        if not text:
            continue
        if merged and merged[-1][1] == fmt:
            merged[-1][0] += text
        else:
            merged.append([text, fmt])

    parts: List[str] = []
    for text, (bold, italic, strike) in merged:
        if bold and italic:
            text = _wrap_inline(text, "***")
        elif bold:
            text = _wrap_inline(text, "**")
        elif italic:
            text = _wrap_inline(text, "*")
        if strike and text.strip():
            text = _wrap_inline(text, "~~")
        parts.append(text)
    return "".join(parts)


def docx_to_markdown(docx_input: Union[str, bytes, BinaryIO]) -> str:
    """
    Converts a Word document (.docx) to Markdown using Python stdlib zipfile and ElementTree.
    Extracts headings, paragraphs, lists, tables, and hyperlinks.
    """
    if isinstance(docx_input, (str, bytes)):
        source: Union[str, io.BytesIO] = io.BytesIO(docx_input) if isinstance(docx_input, bytes) else docx_input
    else:
        source = docx_input

    try:
        zf_cm = zipfile.ZipFile(source)
    except Exception as e:
        raise ValueError(f"Invalid DOCX file: {e}") from e

    with zf_cm as zf:
        # Read relationships for hyperlinks
        rels: Dict[str, str] = {}
        if "word/_rels/document.xml.rels" in zf.namelist():
            try:
                rels_tree = ET.fromstring(safe_read_zip_member(zf, "word/_rels/document.xml.rels"))
                for elem in rels_tree:
                    r_id = elem.attrib.get("Id")
                    target = elem.attrib.get("Target")
                    if r_id and target:
                        rels[r_id] = target
            except Exception:
                pass

        # Read document.xml
        if "word/document.xml" not in zf.namelist():
            return ""

        doc_tree = ET.fromstring(safe_read_zip_member(zf, "word/document.xml"))
        body = None
        for elem in doc_tree.iter():
            if _local_tag(elem) == "body":
                body = elem
                break
        if body is None:
            return ""

        output: List[str] = []

        for child in _iter_blocks(body):
            tag = _local_tag(child)
            if tag == "p":
                para_md = _parse_paragraph(child, rels)
                if para_md:
                    output.append(para_md)
            elif tag == "tbl":
                table_md = _parse_table(child, rels)
                if table_md:
                    output.append(table_md)

        text = "\n\n".join(output).strip()
        return re.sub(r"\n{3,}", "\n\n", text)


def _parse_paragraph(p_elem: ET.Element, rels: Dict[str, str]) -> str:
    heading_prefix = ""
    is_list = False
    list_indent = 0
    p_pr = None
    for child in p_elem:
        if _local_tag(child) == "pPr":
            p_pr = child
            break

    if p_pr is not None:
        for pr_child in p_pr:
            tag = _local_tag(pr_child)
            if tag == "pStyle":
                val = ""
                for k, v in pr_child.attrib.items():
                    if k.endswith("val") or k == "val":
                        val = v
                        break
                val_lower = val.lower()
                # Exact level capture: "heading10" must not match level 1 the
                # way a naive substring check does.
                match = re.search(r"heading\s*(\d+)", val_lower)
                if match:
                    level = int(match.group(1))
                    if 1 <= level <= 6:
                        heading_prefix = "#" * level + " "
                if not heading_prefix and val_lower == "title":
                    heading_prefix = "# "
            elif tag == "numPr":
                num_id: Optional[int] = None
                for num_child in pr_child:
                    num_tag = _local_tag(num_child)
                    if num_tag == "ilvl":
                        for k, v in num_child.attrib.items():
                            if k.endswith("val") or k == "val":
                                try:
                                    list_indent = int(v)
                                except ValueError:
                                    list_indent = 0
                    elif num_tag == "numId":
                        for k, v in num_child.attrib.items():
                            if k.endswith("val") or k == "val":
                                try:
                                    num_id = int(v)
                                except ValueError:
                                    num_id = None
                # numId="0" explicitly disables inherited numbering (style
                # override); only a real list id produces a bullet.
                if num_id != 0:
                    is_list = True

    run_items: List[Tuple[str, RunFormat]] = []
    for item in _iter_inline(p_elem):
        item_tag = _local_tag(item)
        if item_tag == "r":
            run_items.append(_parse_run(item))
        elif item_tag == "hyperlink":
            r_id = ""
            anchor = ""
            for k, v in item.attrib.items():
                if k.endswith("}id") or k.endswith(":id") or k.lower() == "id":
                    r_id = v
                elif k.endswith("}anchor") or k.endswith(":anchor") or k.lower() == "anchor":
                    anchor = v
            url = rels.get(r_id, "")
            if anchor:
                url = f"{url}#{anchor}" if url else f"#{anchor}"
            link_text = _render_runs(
                [_parse_run(r) for r in _iter_inline(item) if _local_tag(r) == "r"]
            )
            if not link_text:
                continue
            if url:
                run_items.append((f"[{link_text}]({clean_url(url)})", (False, False, False)))
            else:
                run_items.append((link_text, (False, False, False)))

    content = _render_runs(run_items).strip()
    if not content:
        return ""

    if heading_prefix:
        return f"{heading_prefix}{content}"
    if is_list:
        indent_str = "  " * max(0, list_indent)
        return f"{indent_str}- {content}"
    return content


def _is_prop_active(elem: ET.Element | None) -> bool:
    if elem is None:
        return False
    for k, v in elem.attrib.items():
        if k.endswith("val") or k == "val":
            if v and v.lower() in ("0", "false", "off", "none"):
                return False
    return True


def _parse_run(r_elem: ET.Element) -> Tuple[str, RunFormat]:
    """Extract run text and its (bold, italic, strike) format flags."""
    r_pr = None
    for child in r_elem:
        if _local_tag(child) == "rPr":
            r_pr = child
            break

    is_bold = False
    is_italic = False
    is_strike = False

    if r_pr is not None:
        for prop in r_pr:
            ptag = _local_tag(prop)
            if ptag in ("b", "bCs") and _is_prop_active(prop):
                is_bold = True
            elif ptag in ("i", "iCs") and _is_prop_active(prop):
                is_italic = True
            elif ptag in ("strike", "dstrike") and _is_prop_active(prop):
                is_strike = True

    text_parts: List[str] = []
    for elem in r_elem:
        tag = _local_tag(elem)
        if tag == "t" and elem.text:
            text_parts.append(elem.text)
        elif tag == "tab":
            text_parts.append("\t")
        elif tag in ("br", "cr"):
            text_parts.append("\n")
        elif tag == "noBreakHyphen":
            text_parts.append("-")

    return "".join(text_parts), (is_bold, is_italic, is_strike)


def _parse_table(tbl_elem: ET.Element, rels: Dict[str, str]) -> str:
    rows: List[List[str]] = []

    def _iter_table_rows(elem: ET.Element) -> Iterator[ET.Element]:
        for child in elem:
            tag = _local_tag(child)
            if tag == "tr":
                yield child
            elif tag in _BLOCK_WRAPPERS:
                content = None
                for sub in child.iter():
                    if _local_tag(sub) == "sdtContent":
                        content = sub
                        break
                if content is not None:
                    yield from _iter_table_rows(content)

    for tr in _iter_table_rows(tbl_elem):
        if _local_tag(tr) != "tr":
            continue
        row_cells: List[str] = []
        for tc in tr:
            if _local_tag(tc) != "tc":
                continue
            # Horizontal merges widen the cell: emit the requested number of
            # columns (text + placeholders) so following columns stay aligned.
            span = 1
            vmerge_continue = False
            for tc_pr in tc:
                if _local_tag(tc_pr) == "tcPr":
                    for pr in tc_pr:
                        ptag = _local_tag(pr)
                        if ptag == "gridSpan":
                            for k, v in pr.attrib.items():
                                if k.endswith("val") or k == "val":
                                    try:
                                        span = max(1, int(v))
                                    except ValueError:
                                        span = 1
                        elif ptag == "vMerge":
                            # <w:vMerge/> (no val) or val="continue" marks a
                            # vertically merged continuation cell: its content
                            # belongs to the restart cell, so keep it empty.
                            val = ""
                            for k, v in pr.attrib.items():
                                if k.endswith("val") or k == "val":
                                    val = v
                                    break
                            vmerge_continue = val.lower() != "restart"
                    break
            if vmerge_continue:
                row_cells.append("")
                row_cells.extend([""] * (span - 1))
                continue
            cell_paragraphs = []
            for p in _iter_blocks(tc):
                item_tag = _local_tag(p)
                if item_tag == "p":
                    p_text = _parse_paragraph(p, rels)
                    if p_text:
                        cell_paragraphs.append(p_text)
                elif item_tag == "tbl":
                    # Nested table: pipe tables cannot nest, so its markdown is
                    # flattened into the enclosing cell (pipes get escaped below).
                    nested_md = _parse_table(p, rels)
                    if nested_md:
                        cell_paragraphs.append(nested_md)
            cell_content = " ".join(cell_paragraphs).strip().replace("\r", "").replace("\n", " ").replace("|", "\\|")
            row_cells.append(cell_content)
            row_cells.extend([""] * (span - 1))
        if row_cells:
            rows.append(row_cells)

    if not rows:
        return ""

    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return ""

    normalized_rows = [r + [""] * (col_count - len(r)) for r in rows]
    header = normalized_rows[0]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * col_count) + " |"]

    for row in normalized_rows[1:]:
        out.append("| " + " | ".join(row) + " |")

    return "\n".join(out)
