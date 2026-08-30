import io
import json
import os
import zipfile
from pathlib import Path
from typing import BinaryIO, List, Set, Union

from core.infrastructure.converter.csv_tsv import csv_to_markdown
from core.infrastructure.converter.docx import docx_to_markdown
from core.infrastructure.converter.epub import epub_to_markdown
from core.infrastructure.converter.html import html_to_markdown
from core.infrastructure.converter.ipynb import ipynb_to_markdown
from core.infrastructure.converter.pdf import pdf_to_markdown
from core.infrastructure.converter.pptx import pptx_to_markdown
from core.infrastructure.converter.xlsx import xlsx_to_markdown

SUPPORTED_EXTENSIONS: Set[str] = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".ppsx",
    ".epub",
    ".html",
    ".htm",
    ".xhtml",
    ".csv",
    ".tsv",
    ".ipynb",
    ".json",
    ".xml",
    ".zip",
}


def is_convertible(path_or_ext: Union[str, Path]) -> bool:
    """Check if a file or extension is supported by the document converter."""
    s = str(path_or_ext).strip()
    ext = os.path.splitext(s)[1].lower()
    if not ext and s:
        ext = s.lower() if s.startswith(".") else f".{s.lower()}"
    return ext in SUPPORTED_EXTENSIONS


def convert_bytes(
    data: bytes,
    extension_or_filename: str = ".html",
) -> str:
    """
    Converts raw document bytes to Markdown based on extension or filename.
    """
    ext = os.path.splitext(extension_or_filename)[1].lower()
    if not ext and extension_or_filename:
        ext = extension_or_filename.lower() if extension_or_filename.startswith(".") else f".{extension_or_filename.lower()}"

    if ext in (".html", ".htm", ".xhtml"):
        return html_to_markdown(data)
    if ext == ".docx":
        return docx_to_markdown(data)
    if ext in (".xlsx", ".xlsm"):
        return xlsx_to_markdown(data)
    if ext in (".pptx", ".ppsx"):
        return pptx_to_markdown(data)
    if ext == ".pdf":
        return pdf_to_markdown(data)
    if ext == ".epub":
        return epub_to_markdown(data)
    if ext in (".csv", ".tsv"):
        delim = "\t" if ext == ".tsv" else None
        return csv_to_markdown(data, delimiter=delim)
    if ext == ".ipynb":
        return ipynb_to_markdown(data)
    if ext == ".json":
        try:
            parsed = json.loads(data.decode("utf-8", errors="replace"))
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            return f"```json\n{formatted}\n```"
        except Exception:
            return f"```json\n{data.decode('utf-8', errors='replace')}\n```"
    if ext == ".xml":
        return f"```xml\n{data.decode('utf-8', errors='replace')}\n```"
    if ext == ".zip":
        return _convert_zip(io.BytesIO(data))

    # Fallback to plain text
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def convert_file(file_path: Union[str, Path]) -> str:
    """
    Converts a file from filesystem to Markdown.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()

    if ext == ".zip":
        with open(path, "rb") as f:
            return _convert_zip(f)
    if ext == ".docx":
        return docx_to_markdown(str(path))
    if ext in (".xlsx", ".xlsm"):
        return xlsx_to_markdown(str(path))
    if ext in (".pptx", ".ppsx"):
        return pptx_to_markdown(str(path))
    if ext == ".pdf":
        return pdf_to_markdown(str(path))
    if ext == ".epub":
        return epub_to_markdown(str(path))
    if ext in (".csv", ".tsv"):
        delim = "\t" if ext == ".tsv" else None
        with open(path, "rb") as f:
            return csv_to_markdown(f.read(), delimiter=delim)
    if ext == ".ipynb":
        with open(path, "rb") as f:
            return ipynb_to_markdown(f.read())
    if ext in (".html", ".htm", ".xhtml"):
        with open(path, "rb") as f:
            return html_to_markdown(f.read())
    if ext == ".json":
        with open(path, "rb") as f:
            return convert_bytes(f.read(), ".json")
    if ext == ".xml":
        with open(path, "rb") as f:
            return convert_bytes(f.read(), ".xml")

    # Fallback for plain text files
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            return f.read()


def _convert_zip(source: Union[str, BinaryIO, io.BytesIO], depth: int = 0) -> str:
    """Recursively convert files inside a ZIP archive to Markdown."""
    if depth > 2:
        return ""
    try:
        zf = zipfile.ZipFile(source)
    except Exception:
        return ""
    output: List[str] = []

    for name in sorted(zf.namelist()):
        basename = os.path.basename(name)
        if name.endswith("/") or "__MACOSX" in name or basename.startswith(".") or basename == "Thumbs.db":
            continue
        ext = os.path.splitext(name)[1].lower()
        if not ext:
            continue
        try:
            file_data = zf.read(name)
            if ext == ".zip":
                md_content = _convert_zip(io.BytesIO(file_data), depth=depth + 1)
            else:
                md_content = convert_bytes(file_data, ext)
            if md_content.strip():
                output.append(f"## File: {name}\n\n{md_content}")
        except Exception:
            continue

    return "\n\n---\n\n".join(output).strip()
