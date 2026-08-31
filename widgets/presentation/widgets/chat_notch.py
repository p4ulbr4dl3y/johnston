"""Top Dynamic Island / Plan Notch widget."""
from __future__ import annotations

from typing import TypedDict

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from widgets.presentation.widgets.footer_layout import format_modal_hint, get_theme_colors
from widgets.utils.row_format import display_width, ellipsize


class PlanItem(TypedDict, total=False):
    step: str
    status: str


class ChatNotch(Static):
    """Dynamic island / plan notch pinned at the top center."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.is_expanded: bool = False

        # Mock static plan data for visual verification (12 steps)
        self.plan_explanation: str = "Switching to AST parser due to nested tags"
        self.plan_items: list[PlanItem] = [
            {"step": "Inspect document XML namespaces", "status": "completed"},
            {"step": "Audit zip decompression bomb protection", "status": "completed"},
            {"step": "Implement shared string table decoder", "status": "completed"},
            {"step": "Analyze zip container structure", "status": "completed"},
            {"step": "Add binary sanitize stream wrapper", "status": "completed"},
            {"step": "Implement docx/xlsx/pptx/epub safe parser", "status": "in_progress"},
            {"step": "Add regression and security tests", "status": "pending"},
            {"step": "Verify fast streaming tokenizer", "status": "pending"},
            {"step": "Benchmark memory limits on 256MB archives", "status": "pending"},
            {"step": "Update converter documentation and specs", "status": "pending"},
            {"step": "Run full test suite & verify", "status": "pending"},
            {"step": "Prepare release tag and changelog entry", "status": "pending"},
        ]

    def on_mount(self) -> None:
        self.refresh_notch()

    def on_click(self) -> None:
        self.toggle_expanded()

    def toggle_expanded(self) -> None:
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            self.add_class("expanded")
        else:
            self.remove_class("expanded")
        self.refresh_notch()

    def _render_collapsed(self) -> Text:
        t_primary, t_secondary, _, _ = get_theme_colors()

        total = len(self.plan_items)
        target_width = 64
        badge = format_modal_hint("ctrl+p: plan")
        badge_plain = "ctrl+p: plan"

        if total == 0:
            no_plan = "No active plan"
            pad = max(2, target_width - display_width(no_plan) - display_width(badge_plain))
            txt = Text.from_markup(f"[{t_secondary}]{no_plan}[/]{' ' * pad}{badge}")
            txt.no_wrap = True
            return txt

        done = sum(1 for item in self.plan_items if item.get("status") == "completed")
        active_item = next((item for item in self.plan_items if item.get("status") == "in_progress"), None)
        if not active_item:
            active_item = next((item for item in self.plan_items if item.get("status") == "pending"), None)

        if active_item:
            active_step = active_item.get("step", "")
        elif done == total:
            active_step = "All tasks completed"
        else:
            active_step = ""

        prefix = f"{done}/{total} "
        prefix_len = display_width(prefix)
        max_step = max(8, target_width - prefix_len - display_width(badge_plain) - 2)
        raw_step = ellipsize(active_step, max_step)
        step_display = escape(raw_step)
        left_len = prefix_len + display_width(raw_step)
        pad = max(2, target_width - left_len - display_width(badge_plain))

        txt = Text.from_markup(
            f"[bold {t_primary}]{done}/{total}[/] [{t_secondary}]{step_display}[/]{' ' * pad}{badge}"
        )
        txt.no_wrap = True
        return txt

    def _render_expanded(self) -> Text:
        t_primary, t_secondary, t_muted, _ = get_theme_colors()

        total = len(self.plan_items)
        done = sum(1 for item in self.plan_items if item.get("status") == "completed")

        target_width = 64
        header_title = f"Plan ({done}/{total})" if total > 0 else "Plan"
        badge = format_modal_hint("ctrl+p: close")
        badge_plain = "ctrl+p: close"
        pad = max(2, target_width - display_width(header_title) - display_width(badge_plain))

        t = Text()
        t.no_wrap = True
        # 1. Header row
        t.append_text(Text.from_markup(f"[bold {t_primary}]{header_title}[/]{' ' * pad}{badge}\n"))

        # 2. Optional explanation
        if self.plan_explanation:
            expl = escape(ellipsize(self.plan_explanation, target_width))
            t.append_text(Text.from_markup(f"[{t_muted}][italic]{expl}[/italic][/]\n"))

        t.append("\n")

        # 3. Checklist items (sliding window if total > 6)
        if total == 0:
            t.append_text(Text.from_markup(f"[{t_muted}]No tasks in plan[/]"))
            return t

        max_visible = 6
        if total <= max_visible:
            start_idx, end_idx = 0, total
            hidden_before, hidden_after = 0, 0
        else:
            active_idx = -1
            for i, it in enumerate(self.plan_items):
                if it.get("status") == "in_progress":
                    active_idx = i
                    break
            if active_idx == -1:
                for i, it in enumerate(self.plan_items):
                    if it.get("status") == "pending":
                        active_idx = i
                        break
            if active_idx == -1:
                active_idx = total - 1

            half = max_visible // 2
            start_idx = max(0, active_idx - half)
            end_idx = start_idx + max_visible
            if end_idx > total:
                end_idx = total
                start_idx = max(0, end_idx - max_visible)
            hidden_before = start_idx
            hidden_after = total - end_idx

        item_lines: list[str] = []
        if hidden_before > 0:
            item_lines.append(f"[{t_muted}]... ({hidden_before} earlier steps)[/]")

        for item in self.plan_items[start_idx:end_idx]:
            step = item.get("step", "")
            status = item.get("status", "pending")
            step_clean = escape(ellipsize(step, target_width - 4))

            if status == "completed":
                item_lines.append(f"[{t_muted}][✓][/] [{t_muted}][strike]{step_clean}[/strike][/]")
            elif status == "in_progress":
                item_lines.append(f"[bold {t_primary}][▶][/] [bold {t_primary}]{step_clean}[/]")
            else:
                item_lines.append(f"[{t_muted}][ ][/] [{t_secondary}]{step_clean}[/]")

        if hidden_after > 0:
            item_lines.append(f"[{t_muted}]... ({hidden_after} remaining steps)[/]")

        if item_lines:
            t.append_text(Text.from_markup("\n".join(item_lines)))

        return t

    def refresh_notch(self) -> None:
        try:
            if self.is_expanded:
                content = self._render_expanded()
            else:
                content = self._render_collapsed()
            self.update(content)
        except Exception:
            pass


class ChatNotchContainer(Container):
    """Overlay container that anchors the floating notch at the top center."""

    can_focus = False
    ALLOW_SELECT = False

    def compose(self) -> ComposeResult:
        yield ChatNotch(id="chat-notch")


class HudOverlay(Container):
    """Overlay container for floating HUD elements."""

    can_focus = False
    ALLOW_SELECT = False
