import io
import posixpath
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, BinaryIO, Dict, List, Union

from core.infrastructure.converter.html import html_to_markdown
from core.infrastructure.converter.utils import collapse_blank_lines, safe_read_zip_member


def _local_tag(elem_or_tag: Any) -> str:
    tag = elem_or_tag.tag if hasattr(elem_or_tag, "tag") else elem_or_tag
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def epub_to_markdown(epub_input: Union[str, bytes, BinaryIO]) -> str:
    """
    Converts an EPUB ebook to Markdown using Python stdlib zipfile, ElementTree, and HTML parser.
    Extracts metadata and chapters in spine order.
    """
    if isinstance(epub_input, (str, bytes)):
        source: Union[str, io.BytesIO] = io.BytesIO(epub_input) if isinstance(epub_input, bytes) else epub_input
    else:
        source = epub_input

    try:
        zf_cm = zipfile.ZipFile(source)
    except Exception as e:
        raise ValueError(f"Invalid EPUB file: {e}") from e

    with zf_cm as zf:
        namelist = zf.namelist()

        # 1. Locate OPF file from META-INF/container.xml
        opf_path = ""
        if "META-INF/container.xml" in namelist:
            try:
                container_tree = ET.fromstring(safe_read_zip_member(zf, "META-INF/container.xml"))
                for elem in container_tree.iter():
                    if _local_tag(elem) == "rootfile":
                        raw_path = elem.attrib.get("full-path", "")
                        if raw_path:
                            norm_path = posixpath.normpath(urllib.parse.unquote(raw_path)).lstrip("/")
                            if norm_path in namelist:
                                opf_path = norm_path
                            elif raw_path in namelist:
                                opf_path = raw_path
                            else:
                                opf_path = norm_path
                            break
            except Exception:
                pass

        if not opf_path:
            for name in namelist:
                if name.endswith(".opf"):
                    opf_path = name
                    break

        if not opf_path or opf_path not in namelist:
            return ""

        opf_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""

        # 2. Parse OPF metadata, manifest, and spine
        opf_tree = ET.fromstring(safe_read_zip_member(zf, opf_path))
        manifest: Dict[str, str] = {}
        spine_ids: List[str] = []
        title = ""
        creator = ""

        for elem in opf_tree.iter():
            tag = _local_tag(elem)
            if tag == "title" and elem.text and not title:
                title = elem.text.strip()
            elif tag == "creator" and elem.text and not creator:
                creator = elem.text.strip()
            elif tag == "item":
                item_id = elem.attrib.get("id")
                href = elem.attrib.get("href")
                if item_id and href:
                    href_clean = href.split("#", 1)[0].split("?", 1)[0]
                    raw_href = f"{opf_dir}/{href_clean}" if opf_dir else href_clean
                    full_href = posixpath.normpath(urllib.parse.unquote(raw_href))
                    manifest[item_id] = full_href
            elif tag == "itemref":
                idref = elem.attrib.get("idref")
                if idref:
                    spine_ids.append(idref)

        output: List[str] = []
        if title:
            meta_lines = [f"# {title}"]
            if creator:
                meta_lines.append(f"**Author:** {creator}")
            output.append("\n\n".join(meta_lines))

        # 3. Process spine chapters
        for idref in spine_ids:
            chap_path = manifest.get(idref, "")
            if chap_path and chap_path in namelist:
                try:
                    html_bytes = safe_read_zip_member(zf, chap_path)
                    chap_md = html_to_markdown(html_bytes, extract_title=False)
                    if chap_md:
                        output.append(chap_md)
                except Exception:
                    continue

        text = "\n\n---\n\n".join(output).strip()
        return collapse_blank_lines(text)
