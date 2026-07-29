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
    """Sends image to Vision model via provider agent API"""
    from core.provider_manager import ProviderManager
    from tools.context import ToolContext

    app_inst = app.app if isinstance(app, ToolContext) else app
    pm = getattr(app_inst, "pm", None) or ProviderManager()
    providers = pm.load_providers()

    active_key = pm.get_active_provider_key()
    active_model = pm.get_provider_model(active_key)

    target_provider_key = None
    target_model = None

    def _provider_is_usable(pkey: str) -> bool:
        if not pkey or pkey not in providers:
            return False
        pinfo = providers[pkey]
        api_type = pinfo.get("api_type", "openai").lower()
        if api_type == "ollama":
            return True
        key_val = pm.get_api_key(pkey) or pinfo.get("api_key", "")
        return bool(key_val and str(key_val).strip())

    def _provider_has_model(pkey: str, model_id: str) -> bool:
        if not pkey or not model_id or not _provider_is_usable(pkey):
            return False
        if pm.get_provider_model(pkey) == model_id:
            return True
        p_models = providers[pkey].get("models") or []
        return model_id in p_models

    # Option 1: Active provider model if it natively supports vision
    if active_key and _provider_is_usable(active_key) and active_model and catalog.supports_vision(active_key, active_model):
        target_provider_key = active_key
        target_model = active_model

    # Option 2: Configured vision model
    if not target_provider_key:
        fb_prov, fb_model = catalog.get_fallback_vision_model()
        if fb_model:
            if fb_prov and _provider_is_usable(fb_prov) and _provider_has_model(fb_prov, fb_model) and catalog.supports_vision(fb_prov, fb_model):
                target_provider_key = fb_prov
                target_model = fb_model
            elif active_key and _provider_is_usable(active_key) and _provider_has_model(active_key, fb_model) and catalog.supports_vision(active_key, fb_model):
                target_provider_key = active_key
                target_model = fb_model

    # Option 3: Search any provider that supports vision and has configured API key
    if not target_provider_key or not _provider_is_usable(target_provider_key):
        for pkey, pinfo in providers.items():
            if not _provider_is_usable(pkey):
                continue
            m_cand = pm.get_provider_model(pkey)
            models_to_check = [m_cand] if m_cand else []
            if pinfo.get("models"):
                models_to_check.extend(pinfo["models"])
            for m_item in models_to_check:
                if m_item and catalog.supports_vision(pkey, m_item):
                    target_provider_key = pkey
                    target_model = m_item
                    break
            if target_provider_key:
                break

    if not target_provider_key or not target_model:
        return f"Error: No vision-capable provider with configured API key available to analyze image '{image_path}'."

    try:
        b64_url, mime_type = process_and_encode_image(image_path, max_dim=1568)

        pinfo = providers[target_provider_key]
        base_url = pinfo.get("base_url", "").rstrip("/")
        api_key = pm.get_api_key(target_provider_key) or pinfo.get("api_key", "")
        api_type = pinfo.get("api_type", "openai").lower()

        if api_type in ("anthropic", "gemini", "ollama"):
            from core.adapters import get_adapter
            adapter = get_adapter(api_type)

            messages = [
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

            parts = []
            async for kind, payload in adapter.stream_chat(
                base_url=base_url,
                api_key=api_key,
                model=target_model,
                messages=messages,
                max_tokens=4096,
            ):
                if kind == "adapter_text":
                    parts.append(payload)

            analysis_text = "".join(parts) if parts else "No content returned from vision model."
            return analysis_text

        import httpx

        url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        extra_headers = pinfo.get("headers")
        if isinstance(extra_headers, dict):
            headers.update(extra_headers)

        payload = {
            "model": target_model,
            "max_tokens": 4096,
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

                    return analysis_text

            return f"Error from vision model (HTTP {resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        return f"Error running vision model for '{image_path}': {e}"


class AnalyzeImageTool(BaseTool):
    name = "analyze_image"
    description = "Analyze an image file on disk (png, jpg, webp, gif, svg) to extract visual contents, UI layout, or answer specific questions about the image."
    schema = {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to image file"},
                    "prompt": {"type": "string", "description": "Optional question or specific prompt describing what to inspect in the image"}
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

        prompt = args.get("prompt") or args.get("question") or "Describe all visual content, text, UI elements, and layout of this image in detail."

        from tools.context import ToolContext
        app_inst = app.app if isinstance(app, ToolContext) else app

        # Always route vision inspection through clean isolated Vision pipeline
        return await analyze_image_with_fallback(path, prompt, app_inst)







