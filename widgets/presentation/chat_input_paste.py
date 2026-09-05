import asyncio
import os
import re
import urllib.parse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from widgets.chat_input import ChatInput

MOUSE_ARTIFACT_REGEX = re.compile(r"(?:M|\[)?<[0-9]{1,3};[0-9]+;[0-9]+[Mm]")


class ClipboardAttachment:
    """Represents a clipboard image attachment"""

    def __init__(self, path: str):
        self.path = path


def decode_pasted_path(text: str) -> str:
    """Decode a pasted file path: strip quotes, unquote file:/// URLs, expand user dirs."""
    text_strip = text.strip().strip("'\"")
    if text_strip.startswith("file://"):
        text_strip = urllib.parse.unquote(text_strip[7:])
    else:
        text_strip = urllib.parse.unquote(text_strip)
    return os.path.expanduser(text_strip.replace("\\ ", " "))


def format_pasted_file_path(pasted_text: str) -> str:
    """Automatically formats pasted file paths as @file"""
    if pasted_text is None:
        return None
    lines = pasted_text.strip().splitlines()
    if not lines:
        return pasted_text

    new_lines = []
    modified = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue

        if stripped.startswith("@"):
            if not stripped.endswith(" "):
                stripped = stripped + " "
                modified = True
            new_lines.append(stripped)
        else:
            clean = decode_pasted_path(stripped)
            ext = os.path.splitext(clean)[1].lower()
            is_explicit_path = clean.startswith("/") or clean.startswith("~/") or clean.startswith("./")
            if is_explicit_path or ((bool(ext) or "/" in clean) and os.path.exists(clean)):
                line = f"@{clean} "
                modified = True
            new_lines.append(line)

    return "\n".join(new_lines) if modified else pasted_text


async def try_paste_clipboard_image(widget: "ChatInput") -> bool:
    """Checks clipboard for PNG/TIFF/JPEG image or Finder/Explorer image file and inserts as attachment"""
    import time

    from core.infrastructure.platform.paths import TEMP_IMAGES_DIR
    from core.infrastructure.platform.platform_utils import get_clipboard_image_or_file

    file_path, img = await asyncio.to_thread(get_clipboard_image_or_file)

    if file_path:
        widget.insert(f"@{file_path} ")
        widget._on_input_change()
        return True

    if img:
        out_dir = TEMP_IMAGES_DIR
        os.makedirs(out_dir, exist_ok=True)
        final_path = os.path.join(out_dir, f"clip_{int(time.time())}.png")
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        await asyncio.to_thread(img.save, final_path, format="PNG")
        att = ClipboardAttachment(final_path)
        widget.clipboard_attachments.append(att)
        widget.update_attachment_bar()
        return True

    return False


def sanitize_mouse_artifacts(widget: "ChatInput") -> None:
    """Strips accidental raw ANSI mouse tracking escape sequences from the text buffer"""
    text = widget.text
    if MOUSE_ARTIFACT_REGEX.search(text):
        clean_text = MOUSE_ARTIFACT_REGEX.sub("", text)
        row, col = widget.cursor_location
        widget.load_text(clean_text)
        lines = clean_text.split("\n")
        max_row = max(0, len(lines) - 1)
        target_row = min(row, max_row)
        target_col = min(col, len(lines[target_row]))
        widget.move_cursor((target_row, target_col))


def handle_tag_deletion(widget: "ChatInput", event_key: str) -> bool:
    """Atomic deletion of [Pasted text #N +X lines] block on Backspace or Delete"""
    if not widget.pasted_texts or not widget.selection.is_empty:
        return False

    row, col = widget.cursor_location
    line_str = widget.document.get_line(row)

    for tag in list(widget.pasted_texts.keys()):
        start_col = line_str.find(tag)
        while start_col != -1:
            end_col = start_col + len(tag)
            if event_key == "backspace" and start_col < col <= end_col:
                widget.delete((row, start_col), (row, end_col))
                widget.move_cursor((row, start_col))
                widget.pasted_texts.pop(tag, None)
                widget._on_input_change()
                return True
            elif event_key == "delete" and start_col <= col < end_col:
                widget.delete((row, start_col), (row, end_col))
                widget.move_cursor((row, start_col))
                widget.pasted_texts.pop(tag, None)
                widget._on_input_change()
                return True
            start_col = line_str.find(tag, start_col + 1)

    return False
