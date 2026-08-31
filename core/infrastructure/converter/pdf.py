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

    stream_to_close = None
    reader = None
    try:
        if isinstance(pdf_input, bytes):
            source: Union[str, io.BytesIO, BinaryIO] = io.BytesIO(pdf_input)
        elif isinstance(pdf_input, str):
            stream_to_close = open(pdf_input, "rb")
            source = stream_to_close
        else:
            source = pdf_input

        reader = PdfReader(source)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                pass

        pages_text: List[str] = []

        try:
            pages = reader.pages
            num_pages = len(pages)
        except Exception:
            pages = []
            num_pages = 0

        for i, page in enumerate(pages, start=1):
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
                if num_pages > 1:
                    pages_text.append(f"<!-- Page {i} -->\n\n{page_content}")
                else:
                    pages_text.append(page_content)

        output = "\n\n---\n\n".join(pages_text).strip()
        return re.sub(r"\n{3,}", "\n\n", output)
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        if stream_to_close is not None:
            try:
                stream_to_close.close()
            except Exception:
                pass
