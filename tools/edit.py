import difflib
import os
from typing import Any, Dict

from tools.base import BaseTool
from tools.linter import run_linter


class EditTool(BaseTool):
    name = "Edit"
    description = "Replace text block (old_string) with new_string."

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = os.path.expanduser(args.get("path", ""))
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not os.path.exists(path):
            return f"Error: file '{path}' not found."
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return f"Error reading file '{path}': {e}"
        if old_string not in content:
            return f"Error: exact block of text (old_string) not found in '{path}'. Make sure it matches exactly (including leading whitespace/indentation)."
        new_content = content.replace(old_string, new_string, 1)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            return f"Error writing file '{path}': {e}"

        diff_lines = list(difflib.unified_diff(
            content.splitlines(),
            new_content.splitlines(),
            fromfile=path + " (old)",
            tofile=path + " (new)",
            lineterm=""
        ))
        diff_output = "\n".join(diff_lines)
        linter_output = await run_linter(path)
        return diff_output + linter_output
