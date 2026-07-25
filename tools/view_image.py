import base64
import json
import mimetypes
import os
from typing import Any, Dict

from core.models_catalog import catalog
from tools.base import BaseTool, resolve_path


def process_and_encode_image(image_path: str, max_dim: int = 1568) -> tuple[str, str]:
    """
    Reads image, auto-resizes if dimensions exceed max_dim (1568px),
    compresses to optimized JPEG (quality 85), and returns (b64_url, mime_type).
    """
    ext = os.path.splitext(image_path)[1].lower()
    try:
        import io

        from PIL import Image, ImageOps
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            w, h = img.size
            if w > max_dim or h > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # Flatten alpha channel onto white background for optimal compression
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            mime_type = "image/jpeg"

            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:{mime_type};base64,{b64_data}", mime_type
    except Exception:
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith("image/"):
            mime_type = f"image/{ext.lstrip('.')}" if ext in (".png", ".jpeg", ".gif", ".webp") else "image/png"
        with open(image_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{b64_data}", mime_type


async def analyze_image_with_fallback(image_path: str, prompt: str, app: Any = None) -> str:
    """Sends image to fallback Vision model via HTTP request"""
    import httpx

    from core.provider_manager import ProviderManager
    from tools.context import ToolContext

    app_inst = app.app if isinstance(app, ToolContext) else app
    pm = getattr(app_inst, "pm", None) or ProviderManager()
    providers = pm.load_providers()

    target_provider_key = None
    target_model = None

    # Option 1: Configured fallback vision model
    fb_prov, fb_model = catalog.get_fallback_vision_model()
    if fb_prov and fb_model and fb_prov in providers:
        target_provider_key = fb_prov
        target_model = fb_model

    # Option 2: Active provider if it supports vision
    if not target_provider_key:
        active_key = pm.get_active_provider_key()
        if active_key in providers:
            pinfo = providers[active_key]
            m_candidate = pinfo.get("model", "")
            if not m_candidate and pinfo.get("models"):
                m_candidate = pinfo["models"][0]
            if m_candidate and catalog.supports_vision(active_key, m_candidate):
                target_provider_key = active_key
                target_model = m_candidate

    # Option 3: Search any provider that supports vision
    if not target_provider_key:
        for pkey, pinfo in providers.items():
            models_to_check = []
            if pinfo.get("model"):
                models_to_check.append(pinfo["model"])
            if pinfo.get("models"):
                models_to_check.extend(pinfo["models"])
            for m_candidate in models_to_check:
                if m_candidate and catalog.supports_vision(pkey, m_candidate):
                    target_provider_key = pkey
                    target_model = m_candidate
                    break
            if target_provider_key:
                break

    if not target_provider_key or not target_model:
        return f"Error: No vision-capable provider available to analyze image '{image_path}'."

    pinfo = providers[target_provider_key]
    base_url = pinfo.get("base_url", "").rstrip("/")
    api_key = pm.get_api_key(target_provider_key) or pinfo.get("api_key", "")

    if not base_url:
        return f"Error: Base URL for vision provider '{target_provider_key}' is not configured."

    url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

    try:
        b64_url, mime_type = process_and_encode_image(image_path, max_dim=1568)

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        extra_headers = pinfo.get("headers")
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)

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

        prompt = args.get("prompt") or "Describe the visual contents of this image in detail."

        # Obtain application instance and active agent
        from tools.context import ToolContext
        app_inst = app.app if isinstance(app, ToolContext) else app
        agent = getattr(app_inst, "agent", None) if app_inst else None
        if not agent and hasattr(app_inst, "provider_key"):
            agent = app_inst

        provider_key = getattr(agent, "provider_key", None) if agent else None
        model_name = getattr(agent, "model", None) if agent else None

        if not provider_key or not model_name:
            from core.provider_manager import ProviderManager
            pm = getattr(app_inst, "pm", None) or ProviderManager()
            provider_key = provider_key or pm.get_active_provider_key()
            providers = pm.load_providers()
            if provider_key in providers:
                pinfo = providers[provider_key]
                model_name = model_name or pinfo.get("model", "")
                if not model_name and pinfo.get("models"):
                    model_name = pinfo["models"][0]

        provider_key = provider_key or "opencode"
        model_name = model_name or ""

        # If model does not support Vision -> invoke fallback vision subagent
        if not catalog.supports_vision(provider_key, model_name):
            return await analyze_image_with_fallback(path, prompt, app_inst)

        try:
            b64_url, mime_type = process_and_encode_image(path, max_dim=1568)
            return json.dumps({
                "status": "success",
                "message": f"[Image Loaded: {path}]",
                "path": path,
                "image_url": b64_url
            })
        except Exception as e:
            return f"Error reading image file '{path}': {e}"


