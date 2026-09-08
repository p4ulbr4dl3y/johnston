"""Backward-compatible re-exports for chat input paste."""
from johnston_tui.presentation.widgets.chat_input_paste import (
    MOUSE_ARTIFACT_REGEX,
    ChatInputPasteMixin,
    ClipboardAttachment,
    decode_pasted_path,
    format_pasted_file_path,
    handle_tag_deletion,
    sanitize_mouse_artifacts,
    try_paste_clipboard_image,
)

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
