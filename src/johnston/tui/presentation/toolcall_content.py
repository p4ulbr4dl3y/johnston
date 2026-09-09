"""Content and header rendering mixin for ToolCallWidget."""
from __future__ import annotations

import asyncio
from typing import Any

from johnston.tui.presentation.tool_renderers import compute_tool_call_content
from johnston.tui.presentation.toolcall_header import build_toolcall_header
from johnston.tui.presentation.widgets.chat_markdown import safe_update_markdown


class ToolCallContentMixin:
    """Header and expanded content rendering logic for ToolCallWidget."""

    def _is_parent_at_bottom(self) -> bool:
        try:
            from textual.containers import VerticalScroll

            parent = getattr(self, "parent", None)
            if isinstance(parent, VerticalScroll):
                return getattr(parent, "is_at_bottom", lambda: True)()
        except Exception:
            pass
        return True

    def _scroll_if_needed(self, force: bool = False) -> None:
        from johnston.tui.presentation.widgets.chat_messages import scroll_parent_if_needed

        scroll_parent_if_needed(self, force=force)

    def _scroll_to_widget(self, top: bool = False) -> None:
        from johnston.tui.presentation.widgets.chat_messages import scroll_parent_to_widget

        scroll_parent_to_widget(self, top=top)

    def _is_subagent_view(self) -> bool:
        if getattr(self, "status", None) != "running":
            return False
        try:
            screen = getattr(self, "screen", None)
            if screen and type(screen).__name__ in ("SubagentViewScreen", "SessionChatScreen"):
                return True
        except Exception:
            pass
        try:
            for node in getattr(self, "ancestors_with_self", []):
                if (
                    getattr(node, "id", None) == "subagent-chat-view"
                    or type(node).__name__ in ("SubagentViewScreen", "SessionChatScreen")
                ):
                    return True
        except Exception:
            pass
        return False

    def _get_target_max_len(self, w: int | None = None) -> tuple[int, bool]:
        """Calculate dynamic max length for header target and compact hints flag based on width."""
        if w is None:
            w = 0
            try:
                if getattr(self, "is_mounted", False):
                    val = getattr(getattr(self, "size", None), "width", 0)
                    if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                        w = val
                    elif self.app:
                        app_val = getattr(getattr(self.app, "size", None), "width", 0)
                        if isinstance(app_val, int) and not isinstance(app_val, bool) and app_val > 0:
                            w = app_val
            except Exception:
                w = 0

        if not isinstance(w, int) or w <= 0:
            return 60, False

        compact_hints = w < 70
        hints_len = 0
        if getattr(self, "_show_hints", False):
            from johnston.tui.presentation.toolcall_header import build_toolcall_hints_list

            hints = build_toolcall_hints_list(
                status=self.status,
                canonical_tool=self.canonical_tool,
                is_subagent=self._is_subagent_view(),
                background_task_id=getattr(self, "background_task_id", None),
                is_expandable=self.is_expandable(),
                is_expanded=self.is_expanded,
                compact=compact_hints,
            )
            if hints:
                hints_len = len(", ".join(hints)) + 3

        display_name = self.DISPLAY_NAMES.get(self.canonical_tool, self.tool_type or "Tool")
        prefix_len = len(display_name) + 6
        overhead = prefix_len + hints_len + 4
        return max(15, w - overhead), compact_hints

    def on_resize(self, event: Any) -> None:
        val = getattr(getattr(event, "size", None), "width", None)
        w = val if isinstance(val, int) and not isinstance(val, bool) and val > 0 else None
        self.render_header(container_width=w)

    def render_header(self, max_len: int | None = None, container_width: int | None = None) -> None:
        c = self._get_status_color()
        is_subagent = self._is_subagent_view()

        calc_len, compact_hints = self._get_target_max_len(w=container_width)
        target_max_len = max_len if max_len is not None else calc_len

        header_text = build_toolcall_header(
            canonical_tool=self.canonical_tool,
            tool_type=self.tool_type,
            args=self.args or {},
            target=self.target,
            status=self.status,
            status_color=c,
            system_tools=self.SYSTEM_TOOLS,
            display_names=self.DISPLAY_NAMES,
            is_mcp=self.is_mcp,
            is_subagent=is_subagent,
            background_task_id=getattr(self, "background_task_id", None),
            is_expandable=self.is_expandable(),
            is_expanded=self.is_expanded,
            show_hints=getattr(self, "_show_hints", False),
            max_len=target_max_len,
            compact_hints=compact_hints,
        )
        self.header_label.update(header_text)

    def _compute_content(self) -> tuple[str, Any]:
        """Pure content computation (safe to run in a thread); returns (kind, value)."""
        return compute_tool_call_content(
            tool_type=self.tool_type,
            canonical_tool=self.canonical_tool,
            args=self.args,
            target=self.target,
            result_text=self.result_text,
            is_error=self._is_error(),
            guess_lexer=self._guess_lexer,
            clean_markup=self._clean_markup_text,
            clean_hints=self._clean_hints_for_ui,
            clean_bash_output=self._clean_bash_output,
            format_json_result_fn=self._format_json_result,
            log_path=getattr(self, "log_path", None),
        )

    def _apply_content(self, kind: str, value: Any) -> None:
        """Apply a computed content payload to the widgets (event-loop only)."""
        try:
            if kind == "raw":
                self.content_widget.update(value)
                self.content_widget.display = True
                self.md_widget.display = False
            elif kind == "md":
                safe_update_markdown(self.md_widget, value)
                self.md_widget.display = True
                self.content_widget.display = False
            else:  # "markup"
                self.content_widget.update(value)
                self.content_widget.display = True
                self.md_widget.display = False
        except Exception:
            pass

    def render_content(self) -> None:
        """Render the tool's terminal content into the widgets."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and getattr(self, "is_mounted", True):
                self.scroll_box.display = True
                self.content_widget.display = True
                self.md_widget.display = False
                gate: asyncio.Task | None = getattr(self, "_render_gate", None)
                if gate is not None and not gate.done():
                    gate.cancel()
                self._render_version = getattr(self, "_render_version", 0) + 1
                version = self._render_version
                self._render_gate = loop.create_task(self._async_render_content(version))
            else:
                kind, value = self._compute_content()
                self._apply_content(kind, value)
                if getattr(self, "is_expanded", False):
                    if getattr(self, "_should_scroll_to_widget", False):
                        self._should_scroll_to_widget = False
                        self._scroll_to_widget(top=False)
                    else:
                        force = getattr(self, "_should_scroll_on_render", False)
                        self._should_scroll_on_render = False
                        self._scroll_if_needed(force=force)
        except Exception:
            pass

    async def _async_render_content(self, version: int) -> None:
        try:
            kind, value = await asyncio.to_thread(self._compute_content)
        except Exception:
            kind, value = "markup", self._clean_markup_text(getattr(self, "result_text", "") or "")
        if version != getattr(self, "_render_version", 0):
            return
        if not getattr(self, "is_mounted", True):
            return
        self._apply_content(kind, value)
        if getattr(self, "is_expanded", False):
            if getattr(self, "_should_scroll_to_widget", False):
                self._should_scroll_to_widget = False
                self._scroll_to_widget(top=False)
            else:
                force = getattr(self, "_should_scroll_on_render", False)
                self._should_scroll_on_render = False
                self._scroll_if_needed(force=force)
