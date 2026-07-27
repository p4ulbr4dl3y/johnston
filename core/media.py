import base64
import mimetypes


def encode_image_to_b64(file_path: str, max_dim: int = 1568, quality: int = 85) -> tuple[str, str]:
    """Reads an image file, optionally resizes/compresses it, and returns (mime_type, base64_str)."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "image/png"

    with open(file_path, "rb") as f:
        data = f.read()

    # Optional Pillow optimization if available
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(data))
        w, h = img.size
        if w > max_dim or h > max_dim:
            ratio = min(max_dim / w, max_dim / h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        mime_type = "image/jpeg"
    except Exception:
        pass

    b64_str = base64.b64encode(data).decode("utf-8")
    return mime_type, b64_str


def create_data_url(mime_type: str, b64_str: str) -> str:
    """Formats mime type and base64 string into a valid Data URL."""
    return f"data:{mime_type};base64,{b64_str}"
