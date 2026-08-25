from textual.screen import Screen
from textual.widget import Widget


def apply_textual_patches() -> None:
    """Applies patches to Textual base classes (allow_select for nested widgets and safe selection forwarding)"""

    def _new_allow_select(self) -> bool:
        node = self
        while node is not None:
            if not getattr(node, "ALLOW_SELECT", True):
                return False
            node = node.parent
        return True

    Widget.allow_select = property(_new_allow_select)

    original_forward_event = getattr(Screen, "_original_forward_event", Screen._forward_event)
    Screen._original_forward_event = original_forward_event

    def _safe_forward_event(self, event):
        try:
            original_forward_event(self, event)
        except AttributeError as err:
            err_msg = str(err)
            if "region" in err_msg or "scroll_offset" in err_msg or getattr(self, "_select_state", None) is not None:
                self._select_state = None
            else:
                raise

    Screen._forward_event = _safe_forward_event

    from functools import partial
    from typing import Literal

    from textual import constants
    from textual.geometry import Offset
    from textual.selection import SelectEnd, SelectStart

    def _new_pointer_start_offset(self: SelectStart) -> Offset:
        return (
            self.container.region.offset
            + self.container_pointer_delta
            - (self.container.scroll_offset - self.container_initial_scroll_offset)
        )

    SelectStart.pointer_start_offset = property(_new_pointer_start_offset)

    def _get_scroll_container_for(widget: Widget | None) -> Widget | None:
        if widget is None:
            return None
        for ancestor in widget.ancestors_with_self:
            if isinstance(ancestor, Widget) and ancestor.allow_vertical_scroll and ancestor.is_scrollable:
                return ancestor
        return None

    def _patched_start_auto_scroll(
        self: Screen, widget: Widget, direction: Literal[+1, -1], speed: float = 1.0
    ) -> None:
        assert speed > 0

        def _auto_scroll_y(w: Widget, d: float) -> None:
            if self._select_state is not None:
                w.scroll_y += d
                w.scroll_target_y = w.scroll_y
                if hasattr(self, "_last_select_mouse_coord"):
                    mx, my = self._last_select_mouse_coord
                    reg = w.content_region
                    sy = max(reg.y, min(reg.bottom - 1, int(my)))
                    sx = max(reg.x, min(reg.right - 1, int(mx)))
                    sw, so = self.get_widget_and_offset_at(sx, sy)
                    if sw is not None:
                        cw = sw
                        co = so
                        cont = cw if isinstance(cw, Screen) else cw.parent
                        self._select_state = self._select_state.update_end(
                            Offset(sx, sy),
                            SelectEnd(cont, cw, co),
                        )
                self._update_select()

        self._stop_auto_scroll()
        lines_to_scroll = direction * (getattr(self.app, "SELECT_AUTO_SCROLL_SPEED", 60.0) / constants.MAX_FPS) * speed
        callback = partial(_auto_scroll_y, widget, lines_to_scroll)
        callback()
        self._auto_select_scroll_timer = self.set_interval(1 / constants.MAX_FPS, callback)

    Screen._start_auto_scroll = _patched_start_auto_scroll

    def _patched_check_auto_scroll(
        self: Screen, select_widget: Widget, mouse_coord: tuple[float, float], delta_y: float
    ) -> None:
        if not getattr(self.app, "ENABLE_SELECT_AUTO_SCROLL", True) or self._select_state is None:
            return
        self._last_select_mouse_coord = mouse_coord
        mx, my = mouse_coord
        start_w = self._select_state.start.content_widget or self._select_state.start.container
        scroll_w = _get_scroll_container_for(start_w) or _get_scroll_container_for(select_widget)
        if scroll_w is None:
            self._stop_auto_scroll()
            return

        reg = scroll_w.content_region
        lines = max(1, getattr(self.app, "SELECT_AUTO_SCROLL_LINES", 3))
        if my >= reg.bottom - lines:
            if scroll_w.scroll_y < scroll_w.max_scroll_y:
                speed = 1.0 if my >= reg.bottom else max(0.2, (lines - (reg.bottom - my)) / lines)
                self._start_auto_scroll(scroll_w, +1, speed)
                return
        elif my <= reg.y + lines:
            if scroll_w.scroll_y > 0:
                speed = 1.0 if my <= reg.y else max(0.2, (lines - (my - reg.y)) / lines)
                self._start_auto_scroll(scroll_w, -1, speed)
                return
        self._stop_auto_scroll()

    Screen._check_auto_scroll = _patched_check_auto_scroll


    from textual.geometry import Offset

    _old_get_widget_and_offset_at = getattr(Screen, "_original_get_widget_and_offset_at", Screen.get_widget_and_offset_at)
    Screen._original_get_widget_and_offset_at = _old_get_widget_and_offset_at

    def _new_get_widget_and_offset_at(self: Screen, x: int, y: int) -> tuple[Widget | None, Offset | None]:
        widget, offset = _old_get_widget_and_offset_at(self, x, y)
        if widget is not None and offset is None and not widget.is_container and widget.allow_select:
            try:
                region = widget.region
                offset = Offset(x - region.x, y - region.y)
            except Exception:
                pass
        return widget, offset

    Screen.get_widget_and_offset_at = _new_get_widget_and_offset_at

    from typing import Any

    from rich.console import Console
    from rich.style import Style as RichStyle
    from textual.selection import Selection
    from textual.strip import Strip
    from textual.visual import RenderOptions, RichVisual
    from textual.widgets import Static

    _old_static_get_selection = getattr(Static, "_original_get_selection", Static.get_selection)
    Static._original_get_selection = _old_static_get_selection

    def _new_static_get_selection(self: Static, selection: Selection) -> tuple[str, str] | None:
        result = _old_static_get_selection(self, selection)
        if result is not None:
            return result
        try:
            visual = self._render()
            renderable = getattr(visual, "_renderable", visual)
            try:
                console = self.app.console
            except Exception:
                console = Console()
            try:
                width = self.size.width or getattr(console, "width", 80)
            except Exception:
                width = getattr(console, "width", 80)
            lines = []
            for line in console.render_lines(renderable, console.options.update(width=width, height=None, justify="left")):
                lines.append("".join(seg.text for seg in line).rstrip())
            text = "\n".join(lines)
            extracted = selection.extract(text)
            return (extracted, "\n") if extracted else None
        except Exception:
            return None

    Static.get_selection = _new_static_get_selection

    _old_rich_visual_render_strips = getattr(RichVisual, "_original_render_strips", RichVisual.render_strips)
    RichVisual._original_render_strips = _old_rich_visual_render_strips

    def _new_rich_visual_render_strips(
        self: RichVisual, width: int, height: int | None, style: Any, options: RenderOptions
    ) -> list[Strip]:
        strips = _old_rich_visual_render_strips(self, width, height, style, options)
        if options.selection is not None:
            selection = options.selection
            sel_style = options.selection_style
            if sel_style is not None and getattr(sel_style, "rich_style", None):
                rich_sel_style = sel_style.rich_style
            else:
                rich_sel_style = RichStyle(reverse=True)

            styled_strips = []
            for y, strip in enumerate(strips):
                span = selection.get_span(y)
                if span is not None and strip.cell_length > 0:
                    start_x, end_x = span
                    start_x = max(0, min(strip.cell_length, start_x))
                    if end_x == -1 or end_x >= strip.cell_length:
                        before = strip.crop(0, start_x)
                        selected = strip.crop(start_x, strip.cell_length).apply_style(rich_sel_style)
                        styled_strips.append(Strip.join([before, selected]))
                    else:
                        end_x = max(start_x, min(strip.cell_length, end_x))
                        before = strip.crop(0, start_x)
                        selected = strip.crop(start_x, end_x).apply_style(rich_sel_style)
                        after = strip.crop(end_x, strip.cell_length)
                        styled_strips.append(Strip.join([before, selected, after]))
                else:
                    styled_strips.append(strip)
            return styled_strips
        return strips

    RichVisual.render_strips = _new_rich_visual_render_strips

    from widgets.presentation.widgets.chat_markdown import _apply_chat_markdown_patches

    _apply_chat_markdown_patches()
