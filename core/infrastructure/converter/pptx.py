import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import BinaryIO, Dict, List, Tuple, Union

from core.infrastructure.converter.utils import safe_read_zip_member

P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _slide_sort_key(name: str) -> Tuple[int, str]:
    """Natural sort for slideN.xml fallbacks so slide2 precedes slide10."""
    match = re.search(r"slide(\d+)\.xml$", name)
    return (int(match.group(1)) if match else 0, name)


def pptx_to_markdown(pptx_input: Union[str, bytes, BinaryIO]) -> str:
    """
    Converts a PowerPoint presentation (.pptx) to Markdown using Python stdlib zipfile and ElementTree.
    Extracts slide titles, body text, lists, tables, and speaker notes.
    """
    if isinstance(pptx_input, (str, bytes)):
        source: Union[str, io.BytesIO] = io.BytesIO(pptx_input) if isinstance(pptx_input, bytes) else pptx_input
    else:
        source = pptx_input

    try:
        zf_cm = zipfile.ZipFile(source)
    except Exception as e:
        raise ValueError(f"Invalid PPTX file: {e}") from e

    with zf_cm as zf:
        namelist = zf.namelist()

        # 1. Map presentation relationships for slide order
        pres_rels: Dict[str, str] = {}
        if "ppt/_rels/presentation.xml.rels" in namelist:
            try:
                rel_tree = ET.fromstring(safe_read_zip_member(zf, "ppt/_rels/presentation.xml.rels"))
                for elem in rel_tree:
                    r_id = elem.attrib.get("Id")
                    target = elem.attrib.get("Target", "").lstrip("/")
                    if r_id and target:
                        if not target.startswith("ppt/"):
                            target = f"ppt/{target}"
                        pres_rels[r_id] = target
            except Exception:
                pass

        slide_files: List[str] = []
        if "ppt/presentation.xml" in namelist:
            try:
                pres_tree = ET.fromstring(safe_read_zip_member(zf, "ppt/presentation.xml"))
                for sld in pres_tree.iter():
                    tag = sld.tag.split("}", 1)[-1] if "}" in sld.tag else sld.tag
                    if tag == "sldId":
                        r_id = sld.attrib.get(f"{R_NS}id") or sld.attrib.get("id")
                        if r_id and r_id in pres_rels:
                            slide_files.append(pres_rels[r_id])
            except Exception:
                pass

        if not slide_files:
            # Fallback: scan namelist for slide*.xml, in natural numeric order.
            slide_files = [name for name in namelist if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
            slide_files.sort(key=_slide_sort_key)

        output: List[str] = []

        for idx, slide_path in enumerate(slide_files, start=1):
            if slide_path not in namelist:
                continue
            try:
                slide_tree = ET.fromstring(safe_read_zip_member(zf, slide_path))
                slide_md = _parse_slide(slide_tree, zf, slide_path, idx)
                if slide_md:
                    output.append(slide_md)
            except Exception:
                continue

        text = "\n\n---\n\n".join(output).strip()
        return re.sub(r"\n{3,}", "\n\n", text)


def _parse_slide(slide_tree: ET.Element, zf: zipfile.ZipFile, slide_path: str, slide_num: int) -> str:
    slide_lines: List[str] = [f"## Slide {slide_num}\n"]

    for shape in slide_tree.iter():
        tag = shape.tag.split("}", 1)[-1] if "}" in shape.tag else shape.tag
        if tag == "sp":
            shape_text, is_title = _parse_shape(shape)
            if shape_text:
                if is_title:
                    slide_lines.append(f"# {shape_text}\n")
                else:
                    slide_lines.append(f"{shape_text}\n")
        elif tag == "tbl":
            table_md = _parse_pptx_table(shape)
            if table_md:
                slide_lines.append(f"{table_md}\n")

    # Check for speaker notes
    slide_dir, slide_filename = slide_path.rsplit("/", 1)
    rels_path = f"{slide_dir}/_rels/{slide_filename}.rels"
    if rels_path in zf.namelist():
        try:
            rels_tree = ET.fromstring(safe_read_zip_member(zf, rels_path))
            for rel in rels_tree:
                target = rel.attrib.get("Target", "")
                if "notesSlide" in target:
                    if not target.startswith("ppt/"):
                        target = "ppt/" + target.replace("../", "").lstrip("/")
                    if target in zf.namelist():
                        notes_tree = ET.fromstring(safe_read_zip_member(zf, target))
                        notes_text = _extract_notes_text(notes_tree)
                        if notes_text:
                            slide_lines.append(f"### Speaker Notes:\n{notes_text}\n")
        except Exception:
            pass

    return "\n".join(slide_lines).strip()


def _parse_shape(sp_elem: ET.Element) -> Tuple[str, bool]:
    is_title = False
    for ph in sp_elem.iter():
        tag = ph.tag.split("}", 1)[-1] if "}" in ph.tag else ph.tag
        if tag == "ph":
            ph_type = ph.attrib.get("type", "").lower()
            if ph_type in ("title", "ctrtitle", "sub_title", "subtitle"):
                is_title = True

    paragraphs: List[str] = []
    for p in sp_elem.iter():
        tag = p.tag.split("}", 1)[-1] if "}" in p.tag else p.tag
        if tag == "p":
            runs = []
            for r in p:
                rtag = r.tag.split("}", 1)[-1] if "}" in r.tag else r.tag
                if rtag in ("r", "fld"):
                    for t in r:
                        ttag = t.tag.split("}", 1)[-1] if "}" in t.tag else t.tag
                        if ttag == "t" and t.text:
                            runs.append(t.text)
                elif rtag == "br":
                    runs.append("\n")
            p_text = "".join(runs).strip()
            if p_text:
                paragraphs.append(p_text)

    return "\n\n".join(paragraphs).strip(), is_title


def _parse_pptx_table(tbl_elem: ET.Element) -> str:
    rows: List[List[str]] = []
    for tr in tbl_elem:
        tag = tr.tag.split("}", 1)[-1] if "}" in tr.tag else tr.tag
        if tag != "tr":
            continue
        row_cells: List[str] = []
        for tc in tr:
            ctag = tc.tag.split("}", 1)[-1] if "}" in tc.tag else tc.tag
            if ctag != "tc":
                continue
            cell_paras: List[str] = []
            for p in tc:
                ptag = p.tag.split("}", 1)[-1] if "}" in p.tag else p.tag
                if ptag == "p":
                    p_runs = []
                    for child in p:
                        crtag = child.tag.split("}", 1)[-1] if "}" in child.tag else child.tag
                        if crtag in ("r", "fld"):
                            for t in child:
                                ttag = t.tag.split("}", 1)[-1] if "}" in t.tag else t.tag
                                if ttag == "t" and t.text:
                                    p_runs.append(t.text)
                        elif crtag == "br":
                            p_runs.append(" ")
                    p_text = "".join(p_runs).strip()
                    if p_text:
                        cell_paras.append(p_text)
            if not cell_paras:
                # Fallback: any t in tc
                all_t = [t.text for t in tc.iter() if (t.tag.split("}", 1)[-1] if "}" in t.tag else t.tag) == "t" and t.text]
                if all_t:
                    cell_paras.append(" ".join(all_t))
            clean_cell = " ".join(cell_paras).strip().replace("\n", " ").replace("|", "\\|")
            row_cells.append(clean_cell)
        if row_cells:
            rows.append(row_cells)

    if not rows:
        return ""

    col_count = max(len(r) for r in rows)
    if col_count == 0:
        return ""

    normalized = [r + [""] * (col_count - len(r)) for r in rows]
    header = normalized[0]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * col_count) + " |"]
    for row in normalized[1:]:
        out.append("| " + " | ".join(row) + " |")

    return "\n".join(out)


def _extract_notes_text(notes_tree: ET.Element) -> str:
    lines: List[str] = []
    for sp in notes_tree.iter():
        tag = sp.tag.split("}", 1)[-1] if "}" in sp.tag else sp.tag
        if tag == "sp":
            # Check if this shape is the body placeholder for notes
            is_body = False
            for ph in sp.iter():
                ptag = ph.tag.split("}", 1)[-1] if "}" in ph.tag else ph.tag
                if ptag == "ph" and ph.attrib.get("type") == "body":
                    is_body = True
            if is_body:
                text, _ = _parse_shape(sp)
                if text:
                    lines.append(text)
    return "\n".join(lines).strip()
