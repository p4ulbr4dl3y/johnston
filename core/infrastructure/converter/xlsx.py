import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from typing import BinaryIO, Dict, List, Optional, Tuple, Union

from core.infrastructure.converter.utils import safe_read_zip_member

SS_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Excel 1900/1904 date-system epochs (serial day 0).
_EPOCH_1900 = datetime(1899, 12, 30)
_EPOCH_1904 = datetime(1904, 1, 1)

# Built-in numFmt ids that render dates/times (ECMA-376 §18.8.30).
_BUILTIN_DATE_NUMFMT_IDS = {
    14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35,
    36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58,
}

# Format codes for the built-in ids we care about (drive date/time part choice).
_BUILTIN_NUMFMT_CODES = {
    9: "0%",
    10: "0.00%",
    14: "mm/dd/yy",
    15: "d-mmm-yy",
    16: "d-mmm",
    17: "mmm-yy",
    18: "h:mm AM/PM",
    19: "h:mm:ss AM/PM",
    20: "h:mm",
    21: "h:mm:ss",
    22: "m/d/yy h:mm",
    45: "mm:ss",
    46: "[h]:mm:ss",
    47: "[h]:mm",
}

_QUOTED_RE = re.compile(r'"[^"]*"')
_BRACKET_RE = re.compile(r"\[[^\]]*\]")


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


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


def _sheet_sort_key(name: str) -> Tuple[int, str]:
    """Natural sort for sheetN.xml fallbacks so sheet2 precedes sheet10."""
    match = re.search(r"sheet(\d+)\.xml$", name)
    return (int(match.group(1)) if match else 0, name)


def _load_numfmt_styles(zf: zipfile.ZipFile) -> Dict[int, Tuple[int, str]]:
    """Map cellXfs style index (the ``s=`` attribute of cells) to
    ``(numFmtId, custom format code)`` so numeric cells can be rendered as
    dates/times/percents instead of raw serials."""
    if "xl/styles.xml" not in zf.namelist():
        return {}
    try:
        tree = ET.fromstring(safe_read_zip_member(zf, "xl/styles.xml"))
    except Exception:
        return {}
    custom: Dict[int, str] = {}
    for elem in tree.iter():
        if _local(elem.tag) == "numFmt":
            try:
                fmt_id = int(elem.attrib.get("numFmtId", ""))
            except ValueError:
                continue
            code = elem.attrib.get("formatCode", "")
            if fmt_id and code:
                custom[fmt_id] = code
    styles: Dict[int, Tuple[int, str]] = {}
    for elem in tree.iter():
        if _local(elem.tag) == "cellXfs":
            for idx, xf in enumerate(elem):
                if _local(xf.tag) != "xf":
                    continue
                try:
                    fmt_id = int(xf.attrib.get("numFmtId", "0"))
                except ValueError:
                    fmt_id = 0
                styles[idx] = (fmt_id, custom.get(fmt_id, ""))
            break
    return styles


def _format_is_datetime(fmt_id: int, code: str) -> bool:
    if code:
        stripped = _QUOTED_RE.sub("", _BRACKET_RE.sub("", code))
        return bool(re.search(r"[ymdhs]", stripped, re.IGNORECASE))
    return fmt_id in _BUILTIN_DATE_NUMFMT_IDS


def _time_of_day(seconds: int, with_seconds: bool) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if with_seconds:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}"


def _format_serial(value: float, code: str, epoch: datetime) -> Optional[str]:
    """Render an Excel date/time serial as ISO text. Returns None to keep the
    raw number for out-of-range or degenerate values."""
    if not (0 <= value < 2958466):
        return None
    days = int(value)
    seconds = round((value - days) * 86400)
    if seconds >= 86400:
        days += 1
        seconds -= 86400
    stripped = _QUOTED_RE.sub("", code).lower() if code else ""

    elapsed = re.search(r"\[([hms])\]", stripped)
    if elapsed:
        # Elapsed-duration formats ([h]:mm...) render the total, not a clock.
        total = days * 86400 + seconds
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"

    has_date = bool(re.search(r"[yd]", stripped)) or ("m" in stripped and "h" not in stripped and "s" not in stripped)
    has_time = bool(re.search(r"[hs]", stripped)) or "am/pm" in stripped
    if not has_date and not has_time:
        has_date = True

    if has_date and not has_time and days == 0:
        return None  # serial 0 displays as "1/0/1900" in Excel — keep raw

    dt = epoch + timedelta(days=days)
    if has_date and has_time:
        return f"{dt:%Y-%m-%d} {_time_of_day(seconds, with_seconds='s' in stripped)}"
    if has_date:
        return f"{dt:%Y-%m-%d}"
    return _time_of_day(seconds, with_seconds='s' in stripped)


def _format_percent(value: float, code: str) -> str:
    section = code.split(";")[0] if code else ""
    match = re.search(r"\.(0*)%", _QUOTED_RE.sub("", _BRACKET_RE.sub("", section)))
    decimals = len(match.group(1)) if match else 0
    return f"{value * 100:.{decimals}f}%"


def _format_number(raw: str, fmt_id: int, code: str, epoch: datetime) -> Optional[str]:
    try:
        value = float(raw)
    except ValueError:
        return None
    code = code or _BUILTIN_NUMFMT_CODES.get(fmt_id, "")
    if _format_is_datetime(fmt_id, code):
        return _format_serial(value, code, epoch)
    if "%" in _QUOTED_RE.sub("", _BRACKET_RE.sub("", code)):
        return _format_percent(value, code)
    return None


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
        zf_cm = zipfile.ZipFile(source)
    except Exception as e:
        raise ValueError(f"Invalid XLSX file: {e}") from e

    with zf_cm as zf:
        namelist = zf.namelist()
        styles = _load_numfmt_styles(zf)

        # 1. Parse shared strings
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in namelist:
            try:
                ss_tree = ET.fromstring(safe_read_zip_member(zf, "xl/sharedStrings.xml"))
                for si in ss_tree:
                    text_parts = []
                    for child in si:
                        tag = _local(child.tag)
                        if tag == "t" and child.text:
                            text_parts.append(child.text)
                        elif tag == "r":
                            for r_child in child:
                                rtag = _local(r_child.tag)
                                if rtag == "t" and r_child.text:
                                    text_parts.append(r_child.text)
                    shared_strings.append("".join(text_parts))
            except Exception:
                pass

        # 2. Parse workbook & rels for sheets
        sheet_entries: List[Tuple[str, str]] = []  # (sheet_name, xml_path)
        rels_map: Dict[str, str] = {}

        if "xl/_rels/workbook.xml.rels" in namelist:
            try:
                wb_rels = ET.fromstring(safe_read_zip_member(zf, "xl/_rels/workbook.xml.rels"))
                for rel in wb_rels:
                    r_id = rel.attrib.get("Id")
                    target = rel.attrib.get("Target", "").lstrip("/")
                    if r_id and target:
                        if not target.startswith("xl/"):
                            target = f"xl/{target}"
                        rels_map[r_id] = target
            except Exception:
                pass

        date_epoch = _EPOCH_1900
        if "xl/workbook.xml" in namelist:
            try:
                wb_tree = ET.fromstring(safe_read_zip_member(zf, "xl/workbook.xml"))
                for prop in wb_tree.iter():
                    tag = _local(prop.tag)
                    if tag == "workbookPr":
                        # date1904="1" switches the serial-number epoch.
                        if str(prop.attrib.get("date1904", "")).lower() in ("1", "true"):
                            date_epoch = _EPOCH_1904
                    if tag == "sheet":
                        name = prop.attrib.get("name", "Sheet")
                        r_id = None
                        for k, v in prop.attrib.items():
                            if k.endswith("}id") or k.endswith(":id") or k.lower() == "id":
                                r_id = v
                                break
                        sheet_path = rels_map.get(r_id, "") if r_id else ""
                        if not sheet_path:
                            sheet_id = prop.attrib.get("sheetId", "1")
                            sheet_path = f"xl/worksheets/sheet{sheet_id}.xml"
                        sheet_entries.append((name, sheet_path))
            except Exception:
                pass

        if not sheet_entries:
            # Fallback: look for all sheet*.xml, in natural numeric order.
            fallback = [name for name in namelist if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
            fallback.sort(key=_sheet_sort_key)
            for name in fallback:
                sheet_num = name.split("sheet")[-1].replace(".xml", "")
                sheet_entries.append((f"Sheet {sheet_num}", name))

        output: List[str] = []

        for sheet_name, sheet_path in sheet_entries:
            if sheet_path not in namelist:
                continue
            try:
                sheet_tree = ET.fromstring(safe_read_zip_member(zf, sheet_path))
                table_md = _parse_sheet_to_table(sheet_tree, shared_strings, styles, date_epoch)
                if table_md:
                    output.append(f"## {sheet_name}\n\n{table_md}")
            except Exception:
                continue

        return "\n\n".join(output).strip()


def _parse_sheet_to_table(
    sheet_tree: ET.Element,
    shared_strings: List[str],
    styles: Optional[Dict[int, Tuple[int, str]]] = None,
    date_epoch: datetime = _EPOCH_1900,
) -> str:
    rows_dict: Dict[int, Dict[int, str]] = {}
    max_col = 0

    for row_elem in sheet_tree.iter():
        row_tag = _local(row_elem.tag)
        if row_tag != "row":
            continue

        r_attr = row_elem.attrib.get("r")
        row_idx = int(r_attr) - 1 if r_attr and r_attr.isdigit() else len(rows_dict)

        col_dict: Dict[int, str] = {}
        last_col_idx = -1
        for c in row_elem:
            c_tag = _local(c.tag)
            if c_tag != "c":
                continue

            ref = c.attrib.get("r", "")
            if ref:
                c_idx, _ = _split_cell_ref(ref)
            else:
                c_idx = last_col_idx + 1
            last_col_idx = c_idx

            cell_type = c.attrib.get("t", "")
            val_text = ""

            v_elem = None
            is_elem = None
            for child in c:
                ctag = _local(child.tag)
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
            elif cell_type == "str" and v_elem is not None:
                val_text = v_elem.text or ""
            elif v_elem is not None and v_elem.text:
                # Numeric cell: render through the cell's number format so
                # dates/times/percents become readable text instead of raw
                # serial numbers like 45999.
                fmt = (0, "")
                s_attr = c.attrib.get("s")
                if s_attr and s_attr.isdigit():
                    fmt = (styles or {}).get(int(s_attr), (0, ""))
                if fmt != (0, ""):
                    formatted = _format_number(v_elem.text, fmt[0], fmt[1], date_epoch)
                    val_text = formatted if formatted is not None else v_elem.text
                else:
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
