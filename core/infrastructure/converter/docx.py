import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import BinaryIO, Dict, Iterator, List, Union

from core.infrastructure.converter.utils import safe_read_zip_member

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Paragraph/block wrappers whose descendants hold real content: content
# controls (w:sdt), smart tags and tracked-change insertions.
_INLINE_WRAPPERS = {"ins", "smartTag", "moveTo"}
_BLOCK_WRAPPERS = {"sdt"}


def _local_tag(elem: ET.Element) -> str:
    tag = elem.tag
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
                is_list = True
                for num_child in pr_child:
                    if _local_tag(num_child) == "ilvl":
                        for k, v in num_child.attrib.items():
                            if k.endswith("val") or k == "val":
                                try:
                                    list_indent = int(v)
                                except ValueError:
                                    list_indent = 0

    runs_text: List[str] = []
    for item in _iter_inline(p_elem):
        item_tag = _local_tag(item)
        if item_tag == "r":
            runs_text.append(_parse_run(item))
        elif item_tag == "hyperlink":
            r_id = item.attrib.get(f"{R_NS}id", "") or item.attrib.get("id", "")
            url = rels.get(r_id, "")
            link_text = "".join(_parse_run(r) for r in _iter_inline(item) if _local_tag(r) == "r")
            if url and link_text:
                runs_text.append(f"[{link_text}]({url})")
            elif link_text:
                runs_text.append(link_text)

    content = "".join(runs_text).strip()
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


def _parse_run(r_elem: ET.Element) -> str:
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
            if ptag == "b" and _is_prop_active(prop):
                is_bold = True
            elif ptag == "i" and _is_prop_active(prop):
                is_italic = True
            elif ptag == "strike" and _is_prop_active(prop):
                is_strike = True

    text_parts: List[str] = []
    for elem in r_elem:
        tag = _local_tag(elem)
        if tag == "t" and elem.text:
            text_parts.append(elem.text)
        elif tag == "tab":
            text_parts.append("\t")
        elif tag == "br":
            text_parts.append("\n")

    text = "".join(text_parts)
    if not text:
        return ""

    if is_bold and is_italic:
        text = f"***{text}***"
    elif is_bold:
        text = f"**{text}**"
    elif is_italic:
        text = f"*{text}*"
    if is_strike:
        text = f"~~{text}~~"

    return text


def _parse_table(tbl_elem: ET.Element, rels: Dict[str, str]) -> str:
    rows: List[List[str]] = []

    for tr in tbl_elem:
        if _local_tag(tr) != "tr":
            continue
        row_cells: List[str] = []
        for tc in tr:
            if _local_tag(tc) != "tc":
                continue
            cell_paragraphs = []
            for p in tc:
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
            cell_content = " ".join(cell_paragraphs).strip().replace("\n", " ").replace("|", "\\|")
            row_cells.append(cell_content)
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
