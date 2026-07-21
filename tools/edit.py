import difflib
import os
from typing import Any, Dict

from tools.base import BaseTool, resolve_path
from tools.linter import run_linter


class EditTool(BaseTool):
    name = "Edit"
    description = "Replace unique text block (old_string) with new_string."
    schema = {
        "type": "function",
        "function": {
            "name": "Edit",
            "description": "Replace an exact, unique block of text (old_string) with new_string in an existing file. Must match exact whitespace and indentation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "old_string": {"type": "string", "description": "Exact text block to replace"},
                    "new_string": {"type": "string", "description": "Replacement text block"}
                },
                "required": ["path", "old_string", "new_string"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = resolve_path(args.get("path"))
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not os.path.exists(path):
            return f"Error: file '{path}' not found."
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return f"Error reading file '{path}': {e}"
        count = content.count(old_string)
        if count == 0:
            return (
                f"Error: exact block of text (old_string) not found in '{path}'. "
                f"Make sure to call the Read tool first to inspect exact lines and indentation."
            )
        if count > 1:
            return f"Error: old_string matches {count} occurrences in '{path}'. Include more surrounding lines to make old_string unique."

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
