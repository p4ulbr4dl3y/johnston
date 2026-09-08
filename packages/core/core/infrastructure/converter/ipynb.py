import json
from typing import Any, Dict, List, Union

from core.infrastructure.converter.utils import collapse_blank_lines, fenced_code_block
from core.infrastructure.tasks.output import strip_ansi


def ipynb_to_markdown(ipynb_input: Union[str, bytes, Dict[str, Any]]) -> str:
    """
    Converts a Jupyter Notebook (.ipynb) to Markdown using Python stdlib json.
    Formats markdown cells and wraps code cells with a language fence taken
    from the notebook's ``language_info`` metadata (default: python).
    """
    if isinstance(ipynb_input, bytes):
        data = json.loads(ipynb_input.decode("utf-8", errors="replace"))
    elif isinstance(ipynb_input, str):
        data = json.loads(ipynb_input)
    else:
        data = ipynb_input
    if not isinstance(data, dict):
        raise ValueError("Invalid notebook: top-level JSON must be an object")

    cells = data.get("cells", [])
    if not isinstance(cells, list):
        raise ValueError("Invalid notebook: 'cells' must be a list")

    lang = _notebook_language(data)
    output: List[str] = []

    for cell in cells:
        if not isinstance(cell, dict):
            continue
        cell_type = cell.get("cell_type", "")
        # "source" may be a list of lines, a plain string, or explicitly null.
        source_lines = cell.get("source")
        if isinstance(source_lines, list):
            source = "".join(str(s) for s in source_lines if s is not None)
        elif isinstance(source_lines, str):
            source = source_lines
        elif source_lines is not None:
            source = str(source_lines)
        else:
            source = ""
        source = source.strip()
        if not source:
            continue

        if cell_type == "markdown":
            output.append(source)
        elif cell_type == "code":
            code_block = fenced_code_block(source, lang=lang)
            # Optional outputs
            outputs = cell.get("outputs", [])
            if not isinstance(outputs, list):
                outputs = []
            out_texts: List[str] = []
            for out in outputs:
                if not isinstance(out, dict):
                    continue
                out_type = out.get("output_type", "")
                if out_type == "stream":
                    text = _as_text(out.get("text", []))
                    if text.strip():
                        out_texts.append(fenced_code_block(text.strip(), lang="output"))
                elif out_type in ("execute_result", "display_data"):
                    data_dict = out.get("data", {})
                    if isinstance(data_dict, dict):
                        if "text/markdown" in data_dict:
                            text = _as_text(data_dict["text/markdown"])
                            if text.strip():
                                out_texts.append(text.strip())
                        elif "text/plain" in data_dict:
                            text = _as_text(data_dict["text/plain"])
                            if text.strip():
                                out_texts.append(fenced_code_block(text.strip(), lang="output"))
                elif out_type == "error":
                    tb = out.get("traceback", [])
                    tb_str = "\n".join(str(line) for line in tb if line is not None) if isinstance(tb, list) else _as_text(tb)
                    clean_tb = strip_ansi(tb_str)
                    if clean_tb.strip():
                        out_texts.append(fenced_code_block(clean_tb.strip(), lang="output"))
                    elif out.get("evalue"):
                        out_texts.append(
                            fenced_code_block(f"{out.get('ename')}: {out.get('evalue')}", lang="output")
                        )
            if out_texts:
                output.append(code_block + "\n\n" + "\n\n".join(out_texts))
            else:
                output.append(code_block)
        elif cell_type == "raw":
            output.append(fenced_code_block(source))

    text = collapse_blank_lines("\n\n".join(output).strip())
    return text


# Normalise common kernel language names to fence-friendly identifiers.
_LANG_ALIASES = {"python3": "python", "ipython": "python", "ipython3": "python", "ir": "r"}


def _notebook_language(data: Dict[str, Any]) -> str:
    """Best-effort code language from nbformat metadata (default: python)."""
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        return "python"
    language_info = meta.get("language_info")
    if not isinstance(language_info, dict):
        return "python"
    name = language_info.get("name") or language_info.get("pygments_lexer")
    if isinstance(name, str) and name.strip():
        name = name.strip().lower()
        return _LANG_ALIASES.get(name, name)
    return "python"


def _as_text(value: Any) -> str:
    """Join notebook text fields, which may be a list of lines, a string, or other types."""
    if isinstance(value, list):
        return "".join(str(item) for item in value if item is not None)
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)
