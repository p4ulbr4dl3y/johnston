import os
import threading


def process_image_file_sync(path: str, detail: str | None = None, cancel_event: threading.Event | None = None) -> str:
    """Synchronous worker to load, validate, resize, and convert image files to Base64 JSON."""

    def _interrupted() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    if _interrupted():
        return ""

    import base64
    import io
    import json

    from PIL import Image

    import tools.read as read_pkg

    tools_cfg = read_pkg._tools_settings()
    dim_low = tools_cfg.image_dimension_low if tools_cfg else 512
    dim_high = tools_cfg.image_dimension_high if tools_cfg else 2048
    dim_default = tools_cfg.max_image_dimension if tools_cfg else 1568
    png_keep_bytes = tools_cfg.image_png_keep_bytes if tools_cfg else 1 * 1024 * 1024

    try:
        with Image.open(path) as img:
            img_format = (img.format or "JPEG").upper()
            w, h = img.size

            if detail == "low":
                max_dim = dim_low
            elif detail in ("high", "original"):
                max_dim = dim_high
            else:
                max_dim = dim_default  # Ideal token-efficient resolution for vision LLMs

            # Convert color modes
            if img.mode in ("RGBA", "LA", "P", "PA", "CMYK"):
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                    alpha_composite = Image.alpha_composite(bg, img)
                    img = alpha_composite.convert("RGB")
                else:
                    img = img.convert("RGB")
                target_format = "JPEG"
                media_type = "image/jpeg"
            elif img_format == "PNG" and max(w, h) <= max_dim and os.path.getsize(path) < png_keep_bytes:
                img = img.convert("RGB") if img.mode != "RGB" else img
                target_format = "PNG"
                media_type = "image/png"
            else:
                img = img.convert("RGB") if img.mode != "RGB" else img
                target_format = "JPEG"
                media_type = "image/jpeg"

            if _interrupted():
                return ""

            if max(w, h) > max_dim:
                ratio = max_dim / float(max(w, h))
                new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                w, h = img.size

            buf = io.BytesIO()
            if target_format == "JPEG":
                img.save(buf, format="JPEG", quality=85, optimize=True)
            else:
                img.save(buf, format="PNG", optimize=True)

            img_bytes = buf.getvalue()
            b64_str = base64.b64encode(img_bytes).decode("ascii")
            file_kb = len(img_bytes) / 1024.0

            summary = f"[image {path} | {w}x{h} | {target_format.lower()} | {file_kb:.1f} KB]"

            return json.dumps(
                {
                    "type": "image",
                    "path": path,
                    "dimensions": [w, h],
                    "media_type": media_type,
                    "base64": b64_str,
                    "detail": detail or "high",
                    "summary": summary,
                },
                ensure_ascii=False,
            )
    except Exception as e:
        raise RuntimeError(f"Unable to process image file '{path}': {e}")
