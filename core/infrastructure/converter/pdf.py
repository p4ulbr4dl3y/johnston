import io
import re
from typing import BinaryIO, List, Union


def pdf_to_markdown(pdf_input: Union[str, bytes, BinaryIO]) -> str:
    """
    Converts a PDF document to Markdown using the pure-Python pypdf library.
    Extracts text with layout preservation and page separation.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("pypdf is required to convert PDF documents. Install with 'uv add pypdf'.") from e

    if isinstance(pdf_input, (str, bytes)):
        source: Union[str, io.BytesIO] = io.BytesIO(pdf_input) if isinstance(pdf_input, bytes) else pdf_input
    else:
        source = pdf_input

    reader = PdfReader(source)
    pages_text: List[str] = []

    for i, page in enumerate(reader.pages, start=1):
        try:
            # layout mode preserves whitespace and columns
            text = page.extract_text(extraction_mode="layout")
        except Exception:
            try:
                text = page.extract_text()
            except Exception:
                text = ""

        if text and text.strip():
            cleaned = text.strip()
            # Clean excessive trailing spaces per line
            cleaned_lines = [line.rstrip() for line in cleaned.splitlines()]
            page_content = "\n".join(cleaned_lines)
            if len(reader.pages) > 1:
                pages_text.append(f"<!-- Page {i} -->\n\n{page_content}")
            else:
                pages_text.append(page_content)

    output = "\n\n---\n\n".join(pages_text).strip()
    return re.sub(r"\n{3,}", "\n\n", output)
