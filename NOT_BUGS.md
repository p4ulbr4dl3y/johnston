# NOT BUGS / Intended Architecture Behavior

This document tracks reported candidate issues that were verified to be intended behavior or already safely guarded.

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
