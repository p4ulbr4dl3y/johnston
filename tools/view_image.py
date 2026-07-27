import os
from typing import Any, Dict

from core.media import create_data_url, encode_image_to_b64
from core.models_catalog import catalog
from tools.base import BaseTool, resolve_path


def process_and_encode_image(image_path: str, max_dim: int = 1568) -> tuple[str, str]:
    """
    Reads image, auto-resizes if dimensions exceed max_dim (1568px),
    compresses to optimized JPEG (quality 85), and returns (b64_url, mime_type).
    """
    mime_type, b64_data = encode_image_to_b64(image_path, max_dim=max_dim, quality=85)
    return create_data_url(mime_type, b64_data), mime_type


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
                {
                    "role": "system",
                    "content": "You are a visual inspection assistant. Analyze the image accurately with 100% literal precision. Read and transcribe all visible text, UI elements, structure, and visual details without making assumptions or hallucinating unmentioned context."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": b64_url, "detail": "high"}}
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
                    raw_content = choices[0].get("message", {}).get("content", "")
                    if isinstance(raw_content, list):
                        parts = []
                        for item in raw_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                parts.append(item.get("text", ""))
                            elif isinstance(item, str):
                                parts.append(item)
                        analysis_text = "\n".join(parts) if parts else str(raw_content)
                    elif isinstance(raw_content, str):
                        analysis_text = raw_content
                    else:
                        analysis_text = str(raw_content) if raw_content else "No content in response."

                    return f"[Vision Analysis for {os.path.basename(image_path)}]:\n{analysis_text}"

            return f"Error from vision model (HTTP {resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        return f"Error running vision model for '{image_path}': {e}"


class ViewImageTool(BaseTool):
    name = "view_image"
    description = "Inspect an image file on disk (png, jpg, webp, gif, svg) to analyze its visual contents (UI screenshots, diagrams, photos)."
    schema = {
        "type": "function",
        "function": {
            "name": "view_image",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to image file"},
                    "prompt": {"type": "string", "description": "Optional specific prompt describing what to inspect in the image"}
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

        if ext == ".svg":
            try:
                with open(path, "r", encoding="utf-8") as f:
                    svg_content = f.read(5000)
                return f"[SVG Inspection for {os.path.basename(path)}]:\n{svg_content}"
            except Exception as e:
                return f"Error reading SVG file '{path}': {e}"

        prompt = args.get("prompt") or "Describe all visual content, text, UI elements, and layout of this image in detail."

        from tools.context import ToolContext
        app_inst = app.app if isinstance(app, ToolContext) else app

        # Always route vision inspection through clean isolated Vision pipeline
        return await analyze_image_with_fallback(path, prompt, app_inst)



