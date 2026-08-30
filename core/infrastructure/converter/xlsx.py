import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import BinaryIO, Dict, List, Tuple, Union

SS_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col_letter_to_index(col_str: str) -> int:
    """Convert column letter (A, B, ..., Z, AA, AB) to 0-based column index."""
    idx = 0
    for char in col_str.upper():
        if "A" <= char <= "Z":
            idx = idx * 26 + (ord(char) - ord("A") + 1)
    return max(0, idx - 1)


def _split_cell_ref(ref: str) -> Tuple[int, int]:
    """Split cell reference 'BC12' into (col_idx, row_idx). Row is 0-based."""
    match = re.match(r"^([A-Za-z]+)(\d+)$", ref)
    if not match:
        return 0, 0
    col_str, row_str = match.groups()
    return _col_letter_to_index(col_str), int(row_str) - 1


def xlsx_to_markdown(xlsx_input: Union[str, bytes, BinaryIO]) -> str:
    """
    Converts an Excel workbook (.xlsx) to Markdown using Python stdlib zipfile and ElementTree.
    Renders each sheet as a Markdown pipe table.
    """
    if isinstance(xlsx_input, (str, bytes)):
        source: Union[str, io.BytesIO] = io.BytesIO(xlsx_input) if isinstance(xlsx_input, bytes) else xlsx_input
    else:
        source = xlsx_input

    try:
        zf = zipfile.ZipFile(source)
    except Exception as e:
        raise ValueError(f"Invalid XLSX file: {e}") from e

    namelist = zf.namelist()

    # 1. Parse shared strings
    shared_strings: List[str] = []
    if "xl/sharedStrings.xml" in namelist:
        try:
            ss_tree = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_tree:
                text_parts = []
                for t in si.iter():
                    tag = t.tag.split("}", 1)[-1] if "}" in t.tag else t.tag
                    if tag == "t" and t.text:
                        text_parts.append(t.text)
                shared_strings.append("".join(text_parts))
        except Exception:
            pass

    # 2. Parse workbook & rels for sheets
    sheet_entries: List[Tuple[str, str]] = []  # (sheet_name, xml_path)
    rels_map: Dict[str, str] = {}

    if "xl/_rels/workbook.xml.rels" in namelist:
        try:
            wb_rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in wb_rels:
                r_id = rel.attrib.get("Id")
                target = rel.attrib.get("Target", "")
                if r_id and target:
                    if not target.startswith("xl/"):
                        target = "xl/" + target.lstrip("/")
                    rels_map[r_id] = target
        except Exception:
            pass

    if "xl/workbook.xml" in namelist:
        try:
            wb_tree = ET.fromstring(zf.read("xl/workbook.xml"))
            for sheet_elem in wb_tree.iter():
                tag = sheet_elem.tag.split("}", 1)[-1] if "}" in sheet_elem.tag else sheet_elem.tag
                if tag == "sheet":
                    name = sheet_elem.attrib.get("name", "Sheet")
                    r_id = (
                        sheet_elem.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                        or sheet_elem.attrib.get("id")
                    )
                    sheet_path = rels_map.get(r_id, "")
                    if not sheet_path:
                        sheet_id = sheet_elem.attrib.get("sheetId", "1")
                        sheet_path = f"xl/worksheets/sheet{sheet_id}.xml"
                    sheet_entries.append((name, sheet_path))
        except Exception:
            pass

    if not sheet_entries:
        # Fallback: look for all sheet*.xml
        for name in sorted(namelist):
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_num = name.split("sheet")[-1].replace(".xml", "")
                sheet_entries.append((f"Sheet {sheet_num}", name))

    output: List[str] = []

    for sheet_name, sheet_path in sheet_entries:
        if sheet_path not in namelist:
            continue
        try:
            sheet_tree = ET.fromstring(zf.read(sheet_path))
            table_md = _parse_sheet_to_table(sheet_tree, shared_strings)
            if table_md:
                output.append(f"## {sheet_name}\n\n{table_md}")
        except Exception:
            continue

    return "\n\n".join(output).strip()


def _parse_sheet_to_table(sheet_tree: ET.Element, shared_strings: List[str]) -> str:
    rows_dict: Dict[int, Dict[int, str]] = {}
    max_col = 0

    for row_elem in sheet_tree.iter():
        row_tag = row_elem.tag.split("}", 1)[-1] if "}" in row_elem.tag else row_elem.tag
        if row_tag != "row":
            continue

        r_attr = row_elem.attrib.get("r")
        row_idx = int(r_attr) - 1 if r_attr and r_attr.isdigit() else len(rows_dict)

        col_dict: Dict[int, str] = {}
        for c in row_elem:
            c_tag = c.tag.split("}", 1)[-1] if "}" in c.tag else c.tag
            if c_tag != "c":
                continue

            ref = c.attrib.get("r", "")
            if ref:
                c_idx, _ = _split_cell_ref(ref)
            else:
                c_idx = len(col_dict)

            cell_type = c.attrib.get("t", "")
            val_text = ""

            v_elem = None
            is_elem = None
            for child in c:
                ctag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
                if ctag == "v":
                    v_elem = child
                elif ctag == "is":
                    is_elem = child

            if cell_type == "s" and v_elem is not None and v_elem.text:
                try:
                    s_idx = int(v_elem.text)
                    if 0 <= s_idx < len(shared_strings):
                        val_text = shared_strings[s_idx]
                except ValueError:
                    val_text = v_elem.text or ""
            elif cell_type == "inlineStr" and is_elem is not None:
                val_text = "".join(t.text for t in is_elem.iter() if t.text)
            elif cell_type == "b" and v_elem is not None:
                val_text = "TRUE" if v_elem.text == "1" else "FALSE"
            elif v_elem is not None and v_elem.text:
                val_text = v_elem.text

            clean_val = val_text.strip().replace("\n", " ").replace("|", "\\|")
            if clean_val:
                col_dict[c_idx] = clean_val
                if c_idx > max_col:
                    max_col = c_idx

        if col_dict:
            rows_dict[row_idx] = col_dict

    if not rows_dict:
        return ""

    num_cols = max_col + 1
    sorted_row_indices = sorted(rows_dict.keys())

    # Build grid
    grid: List[List[str]] = []
    for r_idx in sorted_row_indices:
        row_map = rows_dict[r_idx]
        row_vals = [row_map.get(c_idx, "") for c_idx in range(num_cols)]
        grid.append(row_vals)

    if not grid:
        return ""

    # Build markdown table
    header = grid[0]
    # If header is completely blank, synthesize column names
    if not any(header):
        header = [f"Col {i + 1}" for i in range(num_cols)]

    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * num_cols) + " |"]

    for row in grid[1:]:
        out.append("| " + " | ".join(row) + " |")

    return "\n".join(out)
