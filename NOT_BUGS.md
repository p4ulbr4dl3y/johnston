# NOT BUGS / Intended Architecture Behavior

This document tracks reported candidate issues that were verified to be intended behavior or already safely guarded.

---

### 4. `tools/edit.py:242-248` - Trailing newline consumption on empty replacement

- **Report**: Mutation `actual_target += "\n"` on empty string replacement breaks pinpoint edits.
- **Status**: **NOT A BUG** (intended architectural behavior).
- **Rationale**: The edit tool is designed so that deleting a full line (when LLM provides `old_str` without trailing newline and `new_str=""` or missing `new_str`) cleanly removes the line and its trailing line separator (`\n` or `\r\n`), rather than leaving a dangling blank line or orphaned carriage return. This behavior is explicitly pinned and verified by tests across the suite (e.g. `test_delete_crlf_line_consumes_newline`, `test_edit_missing_new_str_is_delete`, `test_edit_tool`).

---

### 13. `widgets/presentation/widgets/attachment_bar.py:33` - `AttachmentChip.on_click` query_one safety

- **Report**: `AttachmentChip.on_click` performs an unprotected `query_one("#message-input")`.
- **Status**: **NOT A BUG** (intended / already protected).
- **Rationale**: The entire `on_click` body is wrapped in a defensive `try ... except Exception: pass` block with an explicit `if app:` check. If `#message-input` is missing, unmounted, or raises `NoMatches` / `WidgetNotMounted`, the exception is caught and suppressed as designed without crashing the application.

---

### 14. `widgets/presentation/widgets/chat_messages.py:358-368` - `BotMessage._render_markdown` app access

- **Report**: `BotMessage._render_markdown` is unprotected when `self.app is None`.
- **Status**: **NOT A BUG** (intended / already protected).
- **Rationale**: The property lookup `dark = bool(getattr(self.app.current_theme, "dark", True))` is enclosed within a dedicated `try ... except Exception: dark = True` block. If `self.app` is `None` or not yet attached to an active application, it gracefully defaults `dark = True` without raising an unhandled exception.
