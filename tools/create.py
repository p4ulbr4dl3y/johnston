import os
from typing import Any, Dict

from tools.base import BaseTool


class CreateTool(BaseTool):
    name = "Create"
    description = "Create new file."

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = os.path.expanduser(args.get("path", ""))
        content = args.get("content", "")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Success: file '{path}' saved ({len(content)} bytes)."
        except Exception as e:
            return f"Error creating file '{path}': {e}"
