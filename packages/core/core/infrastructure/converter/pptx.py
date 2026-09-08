import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, BinaryIO, Dict, List, Tuple, Union

from core.infrastructure.converter.markdown_table import render_markdown_table
from core.infrastructure.converter.utils import safe_read_zip_member


def _local_tag(elem_or_tag: Any) -> str:
    tag = elem_or_tag.tag if hasattr(elem_or_tag, "tag") else elem_or_tag
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1] if "}" in tag else tag


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
                    if _local_tag(sld) == "sldId":
                        r_id = ""
                        for k, v in sld.attrib.items():
                            if k.endswith("}id") or k.endswith(":id") or k.lower() == "id":
                                r_id = v
                                break
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
        tag = _local_tag(shape)
        if tag == "sp":
            shape_text, heading_prefix = _parse_shape(shape)
            if shape_text:
                if heading_prefix:
                    slide_lines.append(f"{heading_prefix}{shape_text}\n")
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


def _parse_shape(sp_elem: ET.Element) -> Tuple[str, str]:
    heading_prefix = ""
    for ph in sp_elem.iter():
        if _local_tag(ph) == "ph":
            ph_type = ph.attrib.get("type", "").lower()
            if ph_type in ("title", "ctrtitle"):
                heading_prefix = "# "
            elif ph_type in ("sub_title", "subtitle"):
                heading_prefix = "## "

    paragraphs: List[str] = []
    for p in sp_elem.iter():
        if _local_tag(p) == "p":
            lvl = 0
            for child in p:
                if _local_tag(child) == "pPr":
                    lvl_attr = child.attrib.get("lvl", "0")
                    try:
                        lvl = int(lvl_attr)
                    except ValueError:
                        lvl = 0
                    break
            runs = []
            for r in p:
                rtag = _local_tag(r)
                if rtag in ("r", "fld"):
                    for t in r:
                        if _local_tag(t) == "t" and t.text:
                            runs.append(t.text)
                elif rtag == "br":
                    runs.append("\n")
            p_text = "".join(runs).strip()
            if p_text:
                if lvl > 0 and not heading_prefix:
                    indent = "  " * lvl
                    paragraphs.append(f"{indent}- {p_text}")
                else:
                    paragraphs.append(p_text)

    return "\n\n".join(paragraphs).strip(), heading_prefix


def _parse_pptx_table(tbl_elem: ET.Element) -> str:
    rows: List[List[str]] = []
    for tr in tbl_elem:
        if _local_tag(tr) != "tr":
            continue
        row_cells: List[str] = []
        for tc in tr:
            if _local_tag(tc) != "tc":
                continue
            cell_paras: List[str] = []
            for p in tc:
                if _local_tag(p) == "p":
                    p_runs = []
                    for child in p:
                        crtag = _local_tag(child)
                        if crtag in ("r", "fld"):
                            for t in child:
                                if _local_tag(t) == "t" and t.text:
                                    p_runs.append(t.text)
                        elif crtag == "br":
                            p_runs.append(" ")
                    p_text = "".join(p_runs).strip()
                    if p_text:
                        cell_paras.append(p_text)
            if not cell_paras:
                # Fallback: any t in tc
                all_t = [t.text for t in tc.iter() if _local_tag(t) == "t" and t.text]
                if all_t:
                    cell_paras.append(" ".join(all_t))
            clean_cell = " ".join(cell_paras).strip().replace("\r", "").replace("\n", " ").replace("|", "\\|")
            row_cells.append(clean_cell)
        if row_cells:
            rows.append(row_cells)

    return render_markdown_table(rows)


def _extract_notes_text(notes_tree: ET.Element) -> str:
    lines: List[str] = []
    for sp in notes_tree.iter():
        if _local_tag(sp) == "sp":
            # Check if this shape is the body placeholder for notes
            is_body = False
            for ph in sp.iter():
                if _local_tag(ph) == "ph":
                    ph_type = ph.attrib.get("type", "").lower()
                    ph_idx = ph.attrib.get("idx", "")
                    if ph_type == "body" or ph_idx == "1":
                        is_body = True
                        break
            if is_body:
                text, _ = _parse_shape(sp)
                if text:
                    lines.append(text)
    return "\n".join(lines).strip()
