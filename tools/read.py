import os
from typing import Any, Dict
from tools.base import BaseTool

class ReadTool(BaseTool):
    name = "Read"
    description = "Read file content."

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = os.path.expanduser(args.get("path", ""))
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 4000:
                        content = content[:4000] + "\n... [content truncated]"
                    return content
            except Exception as e:
                return f"Error reading file '{path}': {e}"
        return f"Error: file '{path}' not found."
