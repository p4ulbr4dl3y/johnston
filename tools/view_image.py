import base64
import json
import mimetypes
import os
from typing import Any, Dict

from core.models_catalog import catalog
from tools.base import BaseTool, resolve_path


async def analyze_image_with_fallback(image_path: str, prompt: str, app: Any = None) -> str:
    """Отправляет изображение фолбэк-модели с поддержкой Vision (по умолчанию cline-pass/mimo-v2.5)"""
    from core.provider_manager import ProviderManager
    pm = getattr(app, "pm", None) or ProviderManager()
    providers = pm.load_providers()

    PREFERRED_PROVIDER_KEY = "clinepass"
    PREFERRED_VISION_MODEL = "cline-pass/mimo-v2.5"

    fallback_agent = None
    if PREFERRED_PROVIDER_KEY in providers:
        try:
            mod = providers[PREFERRED_PROVIDER_KEY]["module"]
            agent_inst = mod.Agent()
            agent_inst.model = PREFERRED_VISION_MODEL
            fallback_agent = agent_inst
        except Exception:
            pass

    if not fallback_agent:
        for pkey, pinfo in providers.items():
            try:
                mod = pinfo["module"]
                agent_inst = mod.Agent()
                if catalog.supports_vision(pkey, agent_inst.model):
                    fallback_agent = agent_inst
                    break
            except Exception:
                pass

    if not fallback_agent:
        return f"Error: No vision-capable model available to analyze image '{image_path}'."

    try:
        ext = os.path.splitext(image_path)[1].lower()
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = f"image/{ext.lstrip('.')}" if ext in (".png", ".jpeg", ".gif", ".webp") else "image/png"

        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        b64_url = f"data:{mime_type};base64,{b64_data}"

        messages = [
            {"role": "system", "content": "You are a visual inspection assistant. Analyze the image accurately according to the user prompt."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": b64_url}}
                ]
            }
        ]

        resp = await fallback_agent.client.chat.completions.create(
            model=fallback_agent.model,
            messages=messages
        )

        analysis_text = resp.choices[0].message.content or "No analysis produced."
        return f"[Vision Sub-Agent Analysis for {os.path.basename(image_path)}]:\n{analysis_text}"
    except Exception as e:
        return f"Error running fallback vision model for '{image_path}': {e}"


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

        # Проверяем, поддерживает ли текущая активная модель Vision
        agent = getattr(app, "agent", None) if app else None
        provider_key = getattr(agent, "provider_key", "opencode") if agent else "opencode"
        model_name = getattr(agent, "model", "") if agent else ""

        if agent and not catalog.supports_vision(provider_key, model_name):
            # Модель не поддерживает Vision -> вызываем фолбэк-субагент
            return await analyze_image_with_fallback(path, prompt, app)

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
