import base64
import json
import mimetypes
import os
from typing import Any, Dict

from core.models_catalog import catalog
from tools.base import BaseTool, resolve_path


async def analyze_image_with_fallback(image_path: str, prompt: str, app: Any = None) -> str:
    """Sends image to fallback Vision model (default cline-pass/mimo-v2.5)"""
    import base64
    import mimetypes

    import httpx

    from core.provider_manager import ProviderManager
    from tools.context import ToolContext

    app_inst = app.app if isinstance(app, ToolContext) else app
    pm = getattr(app_inst, "pm", None) or ProviderManager()
    providers = pm.load_providers()

    PREFERRED_PROVIDER_KEY = "clinepass"
    PREFERRED_VISION_MODEL = "cline-pass/mimo-v2.5"

    target_mod = None
    target_model = PREFERRED_VISION_MODEL

    if PREFERRED_PROVIDER_KEY in providers:
        target_mod = providers[PREFERRED_PROVIDER_KEY]["module"]
    else:
        for pkey, pinfo in providers.items():
            try:
                mod = pinfo["module"]
                agent_inst = mod.Agent()
                if catalog.supports_vision(pkey, agent_inst.model):
                    target_mod = mod
                    target_model = agent_inst.model
                    break
            except Exception:
                pass

    if not target_mod:
        return f"Error: No vision-capable provider available to analyze image '{image_path}'."

    try:
        base_url = getattr(target_mod, "BASE_URL", "").rstrip("/")
        api_key = getattr(target_mod, "API_KEY", "")
        url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

        ext = os.path.splitext(image_path)[1].lower()
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = f"image/{ext.lstrip('.')}" if ext in (".png", ".jpeg", ".gif", ".webp") else "image/png"

        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        b64_url = f"data:{mime_type};base64,{b64_data}"

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": "You are a visual inspection assistant. Analyze the image accurately according to the user prompt."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": b64_url}}
                    ]
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                res_data = resp.json()
                choices = (
                    res_data.get("choices")
                    or (res_data.get("data", {}) or {}).get("choices")
                    or []
                )
                if choices and isinstance(choices, list) and len(choices) > 0:
                    analysis_text = choices[0].get("message", {}).get("content", "No content in choice.")
                    return f"[Vision Sub-Agent Analysis for {os.path.basename(image_path)}]:\n{analysis_text}"

            return f"Error from vision model (HTTP {resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        return f"Error running fallback vision model for '{image_path}': {e}"


class ViewImageTool(BaseTool):
    name = "view_image"
    description = "Inspect an image file on disk (png, jpg, webp, gif, svg) to analyze its visual contents."
    schema = {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "Inspect an image file on disk to analyze visual content (UI screenshots, diagrams, photos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to image file"},
                    "prompt": {"type": "string", "description": "Optional prompt/question for analyzing the image content"}
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

        prompt = args.get("prompt") or "Describe the visual contents of this image in detail."

        # Obtain application instance and active agent
        from tools.context import ToolContext
        app_inst = app.app if isinstance(app, ToolContext) else app
        agent = getattr(app_inst, "agent", None) if app_inst else None
        provider_key = getattr(agent, "provider_key", "opencode") if agent else "opencode"
        model_name = getattr(agent, "model", "") if agent else ""

        # If model does not support Vision -> invoke fallback subagent (mimo-v2.5)
        if not catalog.supports_vision(provider_key, model_name):
            return await analyze_image_with_fallback(path, prompt, app_inst)

        try:
            mime_type, _ = mimetypes.guess_type(path)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = f"image/{ext.lstrip('.')}" if ext in (".png", ".jpeg", ".gif", ".webp") else "image/png"

            with open(path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")

            b64_url = f"data:{mime_type};base64,{b64_data}"
            return json.dumps({
                "status": "success",
                "message": f"[Image Loaded: {path}]",
                "path": path,
                "image_url": b64_url
            })
        except Exception as e:
            return f"Error reading image file '{path}': {e}"
