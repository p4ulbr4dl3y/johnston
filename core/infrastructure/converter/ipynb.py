import json
import re
from typing import Any, Dict, List, Union


def ipynb_to_markdown(ipynb_input: Union[str, bytes, Dict[str, Any]]) -> str:
    """
    Converts a Jupyter Notebook (.ipynb) to Markdown using Python stdlib json.
    Formats markdown cells and wraps code cells with python syntax fences.
    """
    try:
        if isinstance(ipynb_input, bytes):
            raw_text = ipynb_input.decode("utf-8", errors="replace")
            data = json.loads(raw_text)
        elif isinstance(ipynb_input, str):
            data = json.loads(ipynb_input)
        else:
            data = ipynb_input
        if not isinstance(data, dict):
            return ""
    except Exception:
        return ""

    cells = data.get("cells", [])
    if not isinstance(cells, list):
        return ""
    output: List[str] = []

    for cell in cells:
        cell_type = cell.get("cell_type", "")
        source_lines = cell.get("source", [])
        source = "".join(source_lines) if isinstance(source_lines, list) else str(source_lines)
        source = source.strip()
        if not source:
            continue

        if cell_type == "markdown":
            output.append(source)
        elif cell_type == "code":
            code_block = f"```python\n{source}\n```"
            # Optional outputs
            outputs = cell.get("outputs", [])
            out_texts: List[str] = []
            for out in outputs:
                out_type = out.get("output_type", "")
                if out_type == "stream":
                    text = "".join(out.get("text", []))
                    if text.strip():
                        out_texts.append(f"```output\n{text.strip()}\n```")
                elif out_type in ("execute_result", "display_data"):
                    data_dict = out.get("data", {})
                    if "text/plain" in data_dict:
                        text = "".join(data_dict["text/plain"])
                        if text.strip():
                            out_texts.append(f"```output\n{text.strip()}\n```")
                elif out_type == "error":
                    tb = out.get("traceback", [])
                    clean_tb = re.sub(r"\x1b\[[0-9;]*[mGKF]", "", "\n".join(tb))
                    if clean_tb.strip():
                        out_texts.append(f"```output\n{clean_tb.strip()}\n```")
                    elif out.get("evalue"):
                        out_texts.append(f"```output\n{out.get('ename')}: {out.get('evalue')}\n```")
            if out_texts:
                output.append(code_block + "\n\n" + "\n\n".join(out_texts))
            else:
                output.append(code_block)
        elif cell_type == "raw":
            output.append(f"```\n{source}\n```")

    text = "\n\n".join(output).strip()
    return re.sub(r"\n{3,}", "\n\n", text)
