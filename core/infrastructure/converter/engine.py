import os
from pathlib import Path
from typing import Set, Union

from core.infrastructure.converter.docx import docx_to_markdown
from core.infrastructure.converter.epub import epub_to_markdown
from core.infrastructure.converter.html import html_to_markdown
from core.infrastructure.converter.ipynb import ipynb_to_markdown
from core.infrastructure.converter.pdf import pdf_to_markdown
from core.infrastructure.converter.pptx import pptx_to_markdown
from core.infrastructure.converter.xlsx import xlsx_to_markdown

HTML_EXTENSIONS: Set[str] = {
    ".html",
    ".htm",
    ".xhtml",
}

DOC_EXTENSIONS: Set[str] = {
    ".pdf",
    ".docx",
    ".docm",
    ".dotx",
    ".dotm",
    ".xlsx",
    ".xlsm",
    ".xltx",
    ".xltm",
    ".pptx",
    ".ppsx",
    ".potx",
    ".potm",
    ".epub",
    ".ipynb",
}

SUPPORTED_EXTENSIONS: Set[str] = DOC_EXTENSIONS | HTML_EXTENSIONS


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
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like object, got {type(data).__name__}")

    s = str(extension_or_filename).strip()
    ext = os.path.splitext(s)[1].lower()
    if not ext and s:
        ext = s.lower() if s.startswith(".") else f".{s.lower()}"

    if ext in (".html", ".htm", ".xhtml"):
        return html_to_markdown(data)
    if ext in (".docx", ".docm", ".dotx", ".dotm"):
        return docx_to_markdown(data)
    if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        return xlsx_to_markdown(data)
    if ext in (".pptx", ".ppsx", ".potx", ".potm"):
        return pptx_to_markdown(data)
    if ext == ".pdf":
        return pdf_to_markdown(data)
    if ext == ".epub":
        return epub_to_markdown(data)
    if ext == ".ipynb":
        return ipynb_to_markdown(data)

    raise ValueError(f"Unsupported document format: '{ext}'")


def convert_file(file_path: Union[str, Path]) -> str:
    """
    Converts a file from filesystem to Markdown.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"Expected file, found directory: {path}")

    ext = path.suffix.lower()

    if ext in (".docx", ".docm", ".dotx", ".dotm"):
        return docx_to_markdown(str(path))
    if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        return xlsx_to_markdown(str(path))
    if ext in (".pptx", ".ppsx", ".potx", ".potm"):
        return pptx_to_markdown(str(path))
    if ext == ".pdf":
        return pdf_to_markdown(str(path))
    if ext == ".epub":
        return epub_to_markdown(str(path))
    if ext == ".ipynb":
        with open(path, "rb") as f:
            return ipynb_to_markdown(f.read())
    if ext in (".html", ".htm", ".xhtml"):
        with open(path, "rb") as f:
            return html_to_markdown(f.read())

    raise ValueError(f"Unsupported document format: '{ext}'")
