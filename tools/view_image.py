import base64
import mimetypes
import os
from typing import Any, Dict

from tools.base import BaseTool, resolve_path


class ViewImageTool(BaseTool):
    name = "ViewImage"
    description = "Inspect an image file on disk (png, jpg, webp, gif, svg) to analyze its visual contents."
    schema = {
        "type": "function",
        "function": {
            "name": "ViewImage",
            "description": "Inspect an image file on disk to analyze visual content (UI screenshots, diagrams, photos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to image file"}
                },
                "required": ["path"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: image file '{path}' not found."

        ext = os.path.splitext(path)[1].lower()
        valid_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"}
        if ext not in valid_exts:
            return f"Error: '{path}' is not a supported image file format ({', '.join(sorted(valid_exts))})."

        try:
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = f"image/{ext.lstrip('.')}" if ext in (".png", ".jpeg", ".gif", ".webp") else "image/png"

            with open(path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            b64_url = f"data:{mime_type};base64,{b64_data}"
            return f"[Image Content Loaded]\nPath: {path}\nDataURL: {b64_url}"
        except Exception as e:
            return f"Error reading image file '{path}': {e}"
