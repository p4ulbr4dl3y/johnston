import csv
import io
from typing import BinaryIO, List, Union


def csv_to_markdown(csv_input: Union[str, bytes, BinaryIO], delimiter: str | None = None) -> str:
    """
    Converts CSV or TSV data to a clean Markdown pipe table using Python stdlib csv.
    Auto-detects delimiters if not specified.
    """
    if isinstance(csv_input, bytes):
        try:
            text = csv_input.decode("utf-8")
        except UnicodeDecodeError:
            text = csv_input.decode("latin-1", errors="replace")
    elif isinstance(csv_input, str):
        text = csv_input
    else:
        raw = csv_input.read()
        if isinstance(raw, bytes):
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
        else:
            text = raw

    text = text.replace("\x00", "")
    if not text.strip():
        return ""

    delim = delimiter
    if not delim:
        sample = text[:4096]
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample, delimiters=",\t;|")
            delim = dialect.delimiter
        except Exception:
            delim = "\t" if "\t" in sample and "," not in sample else ","

    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows: List[List[str]] = []
    for r in reader:
        if any(cell.strip() for cell in r):
            rows.append([cell.strip().replace("\n", " ").replace("|", "\\|") for cell in r])

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
