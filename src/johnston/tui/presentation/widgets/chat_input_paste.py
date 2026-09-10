import asyncio
import os
import re
import urllib.parse
from typing import Any

from textual import events

from johnston.tui.adapters import core_bridge
from johnston.tui.presentation.screens.constants import STATUS_FOOTER

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


async def try_paste_clipboard_image(widget: Any) -> bool:
    """Checks clipboard for PNG/TIFF/JPEG image or Finder/Explorer image file and inserts as attachment"""
    import time

    file_path, img = await asyncio.to_thread(core_bridge.get_clipboard_image_or_file)

    if file_path:
        widget.insert(f"@{file_path} ")
        widget._on_input_change()
        return True

    if img:
        out_dir = core_bridge.TEMP_IMAGES_DIR
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


def sanitize_mouse_artifacts(widget: Any) -> None:
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


def handle_tag_deletion(widget: Any, event_key: str) -> bool:
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


class ChatInputPasteMixin:
    """Clipboard paste, image attachments, and tag management for ChatInput."""

    @property
    def PASTE_LINE_THRESHOLD(self) -> int:
        import sys

        chat_mod = sys.modules.get("johnston.tui.presentation.widgets.chat_input")
        _get_settings = getattr(chat_mod, "get_settings", core_bridge.get_settings) if chat_mod else core_bridge.get_settings
        return _get_settings().ui.paste_line_threshold

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pasted_texts: dict[str, str] = {}
        self.clipboard_attachments: list = []

    def get_full_text(self) -> str:
        text = self.text
        for tag, raw_val in self.pasted_texts.items():
            if tag in text:
                text = text.replace(tag, raw_val)
        return text

    def sanitize_mouse_artifacts(self) -> None:
        """Strips accidental raw ANSI mouse tracking escape sequences from the text buffer"""
        sanitize_mouse_artifacts(self)

    def _decode_pasted_path(self, text: str) -> str:
        return decode_pasted_path(text)

    def format_pasted_file_path(self, pasted_text: str) -> str:
        """Automatically formats pasted file paths as @file"""
        return format_pasted_file_path(pasted_text)

    def update_attachment_bar(self) -> None:
        try:
            if self.is_mounted and self.app:
                from johnston.tui.presentation.widgets.attachment_bar import AttachmentBar

                bar = self.app.query_one("#attachment-bar", AttachmentBar)
                bar.update_attachments(self.clipboard_attachments)
        except Exception:
            pass
        try:
            if self.is_mounted and self.app:
                footer = self.app.query_one(STATUS_FOOTER)
                footer.refresh_footer()
        except Exception:
            pass

    def remove_clipboard_attachment(self, attachment: Any) -> None:
        """Removes a single attachment and cleans up its temp file."""
        if attachment in self.clipboard_attachments:
            if hasattr(attachment, "path") and os.path.exists(attachment.path) and "temp_images" in attachment.path:
                try:
                    os.remove(attachment.path)
                except OSError:
                    pass
            self.clipboard_attachments.remove(attachment)
            self.update_attachment_bar()

    async def try_paste_clipboard_image(self) -> bool:
        """Checks clipboard for PNG/TIFF/JPEG image or Finder/Explorer image file and inserts as attachment"""
        return await try_paste_clipboard_image(self)

    def _handle_tag_deletion(self, event_key: str) -> bool:
        """Atomic deletion of [Pasted text #N +X lines] block on Backspace or Delete"""
        return handle_tag_deletion(self, event_key)

    async def on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        event.stop()

        pasted_text = self.format_pasted_file_path(event.text)
        if pasted_text.startswith("@") or (
            pasted_text != event.text
            and any(line_item.strip().startswith("@") for line_item in pasted_text.splitlines())
        ):
            self.insert(pasted_text)
            self._on_input_change()
            return

        expanded = self._decode_pasted_path(event.text)
        exists = await asyncio.to_thread(os.path.exists, expanded)
        is_existing_image_path = exists and any(expanded.lower().endswith(ext) for ext in core_bridge.IMAGE_EXTENSIONS)

        if not is_existing_image_path and not event.text.strip():
            if await self.try_paste_clipboard_image():
                return

        lines = pasted_text.splitlines()
        if len(lines) > self.PASTE_LINE_THRESHOLD:
            idx = len(self.pasted_texts) + 1
            tag = f"[Pasted text #{idx} +{len(lines)} lines]"
            self.pasted_texts[tag] = pasted_text
            self.insert(tag)
        else:
            self.insert(pasted_text)
        self._on_input_change()


__all__ = [
    "ChatInputPasteMixin",
    "ClipboardAttachment",
    "MOUSE_ARTIFACT_REGEX",
    "decode_pasted_path",
    "format_pasted_file_path",
    "handle_tag_deletion",
    "sanitize_mouse_artifacts",
    "try_paste_clipboard_image",
]
