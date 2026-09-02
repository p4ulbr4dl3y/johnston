import re
import textwrap
from typing import Any

from rich.markup import escape
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList, Static

from widgets.chat_toolcall import ToolScrollBox
from widgets.mixins.resize_debounce import ResizeDebounceMixin
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    OPTIONS_LIST,
    OPTIONS_LIST_ID,
    TAB_KEYS,
    WRITE_IN_INPUT,
    WRITE_IN_INPUT_ID,
)
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings, normalize_key_to_latin

WRITE_IN_LABEL = "Other (custom answer)"
_RECOMMENDED_RE = re.compile(r"(\(?\bRecommended\b\)?)", re.IGNORECASE)


def _get_option_label(opt: Any) -> str:
    """Extract label from option dict or string."""
    if isinstance(opt, dict):
        return str(opt.get("label") or "").strip()
    return str(opt).strip()


def _get_option_desc(opt: Any) -> str:
    """Extract description from option dict."""
    if isinstance(opt, dict):
        return str(opt.get("description") or "").strip()
    return ""


def format_wizard_option(
    tag: str,
    text: str,
    description: str = "",
    width: int = 72,
    add_gap: bool = False,
) -> str:
    """Format an ask_user wizard option with hanging indent for wrapped lines and optional description."""
    wrap_width = max(20, width - 4)
    lines = textwrap.wrap(text, width=wrap_width)
    if not lines:
        escaped_first = escape(text)
        formatted_first = _RECOMMENDED_RE.sub(r"[dim italic]\1[/dim italic]", escaped_first)
        result_lines = [f"{tag} {formatted_first}"]
    else:
        escaped_first = escape(lines[0])
        formatted_first = _RECOMMENDED_RE.sub(r"[dim italic]\1[/dim italic]", escaped_first)
        result_lines = [f"{tag} {formatted_first}"]
        for line in lines[1:]:
            escaped_line = escape(line)
            formatted_line = _RECOMMENDED_RE.sub(r"[dim italic]\1[/dim italic]", escaped_line)
            result_lines.append(f"    {formatted_line}")
    if description:
        desc_lines = textwrap.wrap(description, width=wrap_width)
        for line in desc_lines:
            result_lines.append(f"    [dim]{escape(line)}[/dim]")
    if add_gap:
        result_lines.append("")
    return "\n".join(result_lines)


class WriteInInput(Input):
    """Custom Input widget that handles Up key to return focus to OptionList and prevents select-all"""

    def _clear_selection(self) -> None:
        val_len = len(self.value)
        self.cursor_position = val_len
        try:
            from textual.widgets._input import Selection

            self.selection = Selection(val_len, val_len)
        except Exception:
            pass

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        self._clear_selection()
        self.call_after_refresh(self._clear_selection)

    async def _on_key(self, event: events.Key) -> None:
        key = (event.key or "").lower()
        cursor = self.cursor_position
        val_len = len(self.value)

        if key in ("up", "key_up"):
            if self.screen and getattr(self.screen, "raw_options", None):
                if hasattr(self.screen, "focus_options_list"):
                    getattr(self.screen, "focus_options_list")()
                    event.stop()
                    event.prevent_default()
                    return
            else:
                if self.screen and hasattr(self.screen, "action_go_back"):
                    getattr(self.screen, "action_go_back")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("down", "key_down"):
            if self.screen and getattr(self.screen, "raw_options", None):
                if hasattr(self.screen, "focus_first_option"):
                    getattr(self.screen, "focus_first_option")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("left", "key_left"):
            if cursor == 0:
                if self.screen and hasattr(self.screen, "action_go_back"):
                    getattr(self.screen, "action_go_back")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("right", "key_right"):
            if cursor == val_len:
                if self.screen and hasattr(self.screen, "action_go_next"):
                    getattr(self.screen, "action_go_next")()
                    event.stop()
                    event.prevent_default()
                    return

        await super()._on_key(event)


class AskUserWizardScreen(ResizeDebounceMixin, BaseModalScreen[str]):
    """Multi-step interactive wizard screen for `ask_user` questions."""

    AUTO_FOCUS = ""
    ALLOW_SELECT = False
    BINDINGS = expand_bindings([
        ("ctrl+h", "minimize", "Minimize"),
        ("left", "go_back", "Back"),
        ("right", "go_next", "Next"),
        ("enter", "go_next", "Next / Confirm"),
        ("tab", "toggle_selection", "Toggle Selection"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, questions: list[dict], answers: dict | None = None, q_idx: int = 0):
        super().__init__()
        self.questions = questions or []
        self.answers = answers or {}
        self.q_idx = q_idx
        self.raw_options = []
        self.options = []

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="wizard-dialog"):
            yield Markdown("", id="wizard-title", classes=MODAL_MARKDOWN)
            with ToolScrollBox(id="wizard-summary-scroll", classes="tool-scroll-box"):
                yield Static("", id="wizard-summary", classes=f"{MODAL_MARKDOWN} wizard-summary", markup=False)
            yield HeaderWrapOptionList(id=OPTIONS_LIST_ID)
            yield WriteInInput(placeholder="Type custom answer and press Enter...", id=WRITE_IN_INPUT_ID, classes="modal-input")
            yield ModalHint("", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        import time

        self._mount_time = time.time()
        self.update_step()
        self.call_after_refresh(self._force_modal_focus)
        self.set_timer(0.05, self._force_modal_focus)

    def _force_modal_focus(self) -> None:
        if not self.is_mounted:
            return
        if self.q_idx < len(self.questions):
            if self.raw_options:
                try:
                    self.query_one(OPTIONS_LIST, OptionList).focus()
                except Exception:
                    pass
            else:
                try:
                    self.query_one(WRITE_IN_INPUT, Input).focus()
                except Exception:
                    pass

    def render_for_size(self) -> None:
        """Re-flow option wrapping after a terminal resize (question step only).

        Preserves the current highlight and any in-progress custom answer text,
        then re-runs the step renderer so options re-wrap to the new width.
        """
        if self.q_idx >= len(self.questions):
            return
        try:
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            highlighted = opt_list.highlighted
            if not opt_list.display or highlighted is None:
                return
        except Exception:
            return
        preserved_value: str | None = None
        preserved_cursor = 0
        try:
            inp = self.query_one(WRITE_IN_INPUT, Input)
            if inp.display and inp.has_focus:
                preserved_value = inp.value
                preserved_cursor = inp.cursor_position
        except Exception:
            pass
        self.update_step(target_highlight=highlighted)
        if preserved_value is not None:
            try:
                inp = self.query_one(WRITE_IN_INPUT, Input)
                inp.value = preserved_value
                inp.cursor_position = preserved_cursor
            except Exception:
                pass

    def on_unmount(self) -> None:
        self.cancel_resize_timer()

    def _split_answer(self, ans: str) -> list[str]:
        """Split a comma-joined answer back into items.

        Known labels are matched first (handles labels containing ', ' and
        negated-style fragments); remaining text stays as one custom item.
        """
        ans = ans.strip()
        if not ans:
            return []
        labels = sorted(
            (lbl for lbl in (_get_option_label(o) for o in self.raw_options) if lbl),
            key=len,
            reverse=True,
        )
        if not labels or ans in labels:
            return [ans]
        out: list[str] = []
        i, n = 0, len(ans)
        while i < n:
            if ans[i] in ", ":
                i += 1
                continue
            # Known label only counts when followed by ", " or end of string,
            # so labels that are prefixes of longer custom text don't match.
            match = next(
                (
                    lbl
                    for lbl in labels
                    if ans.startswith(lbl, i)
                    and (i + len(lbl) == n or ans[i + len(lbl):].startswith(","))
                ),
                None,
            )
            if match:
                out.append(match)
                i += len(match)
                continue
            # Custom fragment: consume up to the next ', ' that starts a known label.
            j = i
            while j < n:
                nxt = ans.find(", ", j)
                if nxt == -1:
                    j = n
                    break
                if any(ans.startswith(lbl, nxt + 2) for lbl in labels):
                    j = nxt
                    break
                j = nxt + 2
            out.append(ans[i:j].strip())
            i = j
        return out

    def _get_step_selections(self, q_idx: int) -> list[str]:
        info = self.answers.get(q_idx, {})
        if isinstance(info, dict):
            if "selected" in info and isinstance(info["selected"], list):
                return [str(s).strip() for s in info["selected"] if str(s).strip()]
            ans = str(info.get("answer") or "").strip()
            if ans:
                return self._split_answer(ans)
            return []
        elif isinstance(info, (list, set, tuple)):
            return [str(s).strip() for s in info if str(s).strip()]
        elif isinstance(info, str) and info.strip():
            return self._split_answer(info.strip())
        return []

    def update_step(self, target_highlight: int | None = None) -> None:
        title_md = self.query_one("#wizard-title", Markdown)
        summary_static = self.query_one("#wizard-summary", Static)
        opt_list = self.query_one(OPTIONS_LIST, OptionList)
        input_field = self.query_one(WRITE_IN_INPUT, Input)
        hint = self.query_one(MODAL_HINT, Label)

        if self.q_idx < len(self.questions):
            title_md.remove_class("confirm-summary")
            try:
                summary_scroll = self.query_one("#wizard-summary-scroll", ToolScrollBox)
                summary_scroll.display = False
                summary_static.display = False
            except Exception:
                pass
            q = self.questions[self.q_idx]
            q_text = q.get("question", "")
            header = str(q.get("header") or "").strip()
            is_multi = bool(q.get("is_multi_select", False))
            header_parts = []
            if header:
                header_parts.append(f"`{header}`")
            if is_multi:
                header_parts.append("*(Select multiple)*")
            header_badge = f" • {' '.join(header_parts)}" if header_parts else ""
            title_md.update(f"### **Question {self.q_idx + 1}/{len(self.questions)}**{header_badge}\n{q_text}")
            hint.update("enter Confirm • tab Toggle • ←→ Nav • ctrl+h Min • esc Cancel")

            self.raw_options = q.get("options") or []
            self.options = self.raw_options + [WRITE_IN_LABEL] if self.raw_options else []
            prev_answer = self.answers.get(self.q_idx, {}).get("answer", "")
            raw_labels = [_get_option_label(o) for o in self.raw_options]
            selected_items = self._get_step_selections(self.q_idx)

            if self.raw_options:
                opt_list.display = True
                opt_list.clear_options()

                if target_highlight is not None and target_highlight < len(self.options):
                    highlight_idx = target_highlight
                    if highlight_idx == len(self.options) - 1 and prev_answer and not is_multi and prev_answer not in raw_labels:
                        input_field.value = prev_answer
                    elif highlight_idx < len(self.raw_options):
                        input_field.value = ""
                elif prev_answer:
                    if not is_multi and prev_answer in raw_labels:
                        highlight_idx = raw_labels.index(prev_answer)
                        input_field.value = ""
                    elif is_multi and selected_items:
                        first_match = next((i for i, lbl in enumerate(raw_labels) if lbl in selected_items), 0)
                        highlight_idx = first_match
                    else:
                        highlight_idx = len(self.options) - 1
                        input_field.value = prev_answer
                        input_field.display = True
                else:
                    highlight_idx = 0
                    input_field.value = ""

                from widgets.utils.responsive import MODAL_CONTENT_GUTTER, MODAL_WIDTH_RATIO, resolve_screen_width

                screen_w = resolve_screen_width(self)
                avail_w = int(screen_w * MODAL_WIDTH_RATIO) - MODAL_CONTENT_GUTTER
                wrap_width = max(20, min(78, avail_w))
                has_multi = any(
                    len(_get_option_label(o)) + 4 > wrap_width or bool(_get_option_desc(o))
                    for o in self.options
                )

                for idx, opt in enumerate(self.options):
                    opt_label = _get_option_label(opt)
                    opt_desc = _get_option_desc(opt)
                    if is_multi:
                        if idx < len(self.raw_options):
                            is_selected = opt_label in selected_items
                        else:
                            is_selected = any(s not in raw_labels for s in selected_items)
                    else:
                        is_selected = bool(
                            prev_answer
                            and (
                                (idx < len(self.raw_options) and prev_answer == opt_label)
                                or (idx == len(self.options) - 1 and prev_answer not in raw_labels)
                            )
                        )
                    tag = r"\[✓]" if is_selected else r"\[ ]"
                    add_gap = (has_multi or bool(opt_desc)) and idx < len(self.options) - 1
                    opt_list.add_option(
                        format_wizard_option(tag, opt_label, description=opt_desc, width=wrap_width, add_gap=add_gap)
                    )

                input_field.placeholder = "Type custom answer and press Enter..."
                input_field.remove_class("standalone")
                input_field.add_class("subordinate")
                opt_list.highlighted = highlight_idx
                if highlight_idx == len(self.options) - 1:
                    self.focus_write_in_input()
                else:
                    input_field.display = False
                    opt_list.focus()

            else:
                opt_list.display = False
                input_field.placeholder = "Type your answer and press Enter..."
                input_field.remove_class("subordinate")
                input_field.add_class("standalone")
                input_field.display = True
                input_field.value = prev_answer
                input_field.focus()
        else:
            from widgets.presentation.tool_renderers import format_ask_user_display

            title_md.add_class("confirm-summary")
            title_md.update("### **Confirm Your Answers**")
            summary_static.update(format_ask_user_display(self.questions, self.answers))
            summary_static.display = True
            summary_scroll = self.query_one("#wizard-summary-scroll")
            summary_scroll.display = True
            opt_list.display = False
            input_field.display = False
            self.focus()

        self._apply_dialog_fit()
        self._update_wizard_hint()

    def _apply_dialog_fit(self) -> None:
        try:
            from widgets.utils.responsive import (
                MODAL_MEDIUM_MAX_WIDTH,
                MODAL_MIN_WIDTH,
                apply_modal_fit,
                modal_content_width,
            )

            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            sample_items = []
            max_q_title = ""
            for q in self.questions:
                q_text = q.get("question", "")
                if len(q_text) > len(max_q_title):
                    max_q_title = q_text
                for opt in q.get("options") or []:
                    opt_label = _get_option_label(opt)
                    opt_desc = _get_option_desc(opt)
                    sample_items.append(f"[✓] {opt_label}")
                    if opt_desc:
                        sample_items.append(f"    {opt_desc}")

            if not sample_items:
                sample_items = ["Type custom answer..."]

            hint = "enter Confirm • tab Toggle • ←→ Nav • ctrl+h Min • esc Cancel"
            content_w = modal_content_width(sample_items, max_q_title or "### **Confirm Your Answers**", hint)
            apply_modal_fit(dialog, content_w, min_width=MODAL_MIN_WIDTH, max_width=MODAL_MEDIUM_MAX_WIDTH)

            screen_h = self.app.size.height if getattr(self, "app", None) else 24
            if not isinstance(screen_h, int) or screen_h <= 0:
                screen_h = 24

            if screen_h < 18:
                dialog.styles.padding = (0, 1)
                dialog.styles.max_height = max(7, screen_h - 1)
                usable_h = screen_h - 1
                overhead = 9
            else:
                dialog.styles.padding = (1, 2)
                dialog.styles.max_height = max(8, min(screen_h - 2, int(screen_h * 0.95)))
                usable_h = screen_h - 2
                overhead = 11

            try:
                opt_list = self.query_one(OPTIONS_LIST, OptionList)
                opt_list.styles.max_height = max(2, usable_h - overhead)
            except Exception:
                pass

            try:
                summary_scroll = self.query_one("#wizard-summary-scroll")
                summary_overhead = 4 if screen_h < 18 else 6
                max_sum_h = 10 if screen_h < 18 else 14
                summary_scroll.styles.max_height = max(3, min(max_sum_h, usable_h - summary_overhead))
            except Exception:
                pass
        except Exception:
            pass

    def _update_wizard_hint(self) -> None:
        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            screen_w = resolve_screen_width(self)
            is_compact = screen_w < BREAKPOINT_HINT

            hint = self.query_one(MODAL_HINT, Label)
            if self.q_idx >= len(self.questions):
                hint.update(
                    "enter • ← • ↑↓ • esc" if is_compact else "enter Confirm • ← Back • ↑↓/pgup Scroll • esc Cancel"
                )
                return

            q = self.questions[self.q_idx] if 0 <= self.q_idx < len(self.questions) else {}
            is_multi = bool(q.get("is_multi_select", False))
            is_last = self.q_idx == len(self.questions) - 1
            action = "Confirm" if is_last else "Next"

            input_field = self.query_one(WRITE_IN_INPUT, Input)
            is_write_in = input_field.display and input_field.has_focus

            back_part = "← Back • " if self.q_idx > 0 else ""
            back_part_compact = "← • " if self.q_idx > 0 else ""

            if not self.raw_options:
                hint.update(
                    f"enter • {back_part_compact}esc"
                    if is_compact
                    else f"enter {action} • {back_part}ctrl+h Min • esc Cancel"
                )
                return

            if is_write_in:
                hint.update(
                    f"enter • ↑ • {back_part_compact}esc"
                    if is_compact
                    else f"enter {action} • ↑ List • {back_part}ctrl+h Min • esc Cancel"
                )
            else:
                tab_part = "tab Toggle • " if is_multi else ""
                tab_part_compact = "tab • " if is_multi else ""
                hint.update(
                    f"enter • {tab_part_compact}{back_part_compact}esc"
                    if is_compact
                    else f"enter {action} • {tab_part}{back_part}ctrl+h Min • esc Cancel"
                )
        except Exception:
            pass

    def focus_write_in_input(self) -> None:
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            input_field.display = True
            input_field.focus()
            self._update_wizard_hint()
        except Exception:
            pass

    def focus_options_list(self) -> None:
        if not self.raw_options:
            return
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            input_field.display = False
            opt_list.highlighted = max(0, len(self.options) - 2)
            opt_list.focus()
            self._update_wizard_hint()
        except Exception:
            pass

    def focus_first_option(self) -> None:
        if not self.raw_options:
            return
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            input_field.display = False
            opt_list.highlighted = 0
            opt_list.focus()
            self._update_wizard_hint()
        except Exception:
            pass


    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted or not self.raw_options or self.q_idx >= len(self.questions):
            return
        try:
            input_field = self.query_one(WRITE_IN_INPUT, Input)
            if event.option_index == len(self.options) - 1:
                self.focus_write_in_input()
            else:
                input_field.display = False
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.raw_options or self.q_idx >= len(self.questions):
            return
        import time

        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        if event.option_index != len(self.options) - 1:
            self.submit_current_step()
        else:
            self.focus_write_in_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        import time

        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        self.submit_current_step()

    def submit_current_step(self) -> None:
        if self.q_idx < len(self.questions):
            q = self.questions[self.q_idx]
            is_multi = bool(q.get("is_multi_select", False))
            if not self.raw_options:
                val = self.query_one(WRITE_IN_INPUT, Input).value.strip()
                answer = val
                selected = [val] if val else []
            else:
                opt_list = self.query_one(OPTIONS_LIST, OptionList)
                idx = opt_list.highlighted
                if idx == len(self.options) - 1:
                    val = self.query_one(WRITE_IN_INPUT, Input).value.strip()
                    if is_multi:
                        selected = self._get_step_selections(self.q_idx)
                        if val and val not in selected:
                            selected.append(val)
                        answer = ", ".join(selected)
                    else:
                        answer = val
                        selected = [val] if val else []
                else:
                    if is_multi:
                        selected = self._get_step_selections(self.q_idx)
                        if not selected and idx is not None and idx < len(self.raw_options):
                            chosen = _get_option_label(self.raw_options[idx])
                            selected = [chosen]
                        answer = ", ".join(selected)
                    else:
                        if idx is not None and idx < len(self.raw_options):
                            answer = _get_option_label(self.raw_options[idx])
                        else:
                            answer = ""
                        selected = [answer] if answer else []

            self.answers[self.q_idx] = {"answer": answer, "selected": selected}
            self.q_idx += 1
            self.update_step()
        else:
            out_parts = []
            for idx, q in enumerate(self.questions):
                q_clean = q.get("question", "")
                ans_info = self.answers.get(idx, {})
                ans_val = ans_info.get("answer", "")
                ans_display = ans_val if ans_val else "(No response)"
                prefix = f"{idx + 1}. " if len(self.questions) > 1 else ""
                out_parts.append(f"{prefix}{q_clean}\n{ans_display}")
            self.dismiss("\n\n".join(out_parts).strip())

    def action_toggle_selection(self) -> None:
        if not self.raw_options or self.q_idx >= len(self.questions):
            return
        try:
            opt_list = self.query_one(OPTIONS_LIST, OptionList)
            if not opt_list.has_focus:
                return
            idx = opt_list.highlighted
            if idx is not None and idx < len(self.raw_options):
                q = self.questions[self.q_idx]
                is_multi = bool(q.get("is_multi_select", False))
                chosen = _get_option_label(self.raw_options[idx])
                if is_multi:
                    selected = self._get_step_selections(self.q_idx)
                    if chosen in selected:
                        selected.remove(chosen)
                    else:
                        selected.append(chosen)
                    self.answers[self.q_idx] = {
                        "answer": ", ".join(selected),
                        "selected": selected,
                    }
                else:
                    current_ans = self.answers.get(self.q_idx, {}).get("answer", "")
                    if current_ans == chosen:
                        self.answers[self.q_idx] = {"answer": "", "selected": []}
                    else:
                        self.answers[self.q_idx] = {"answer": chosen, "selected": [chosen]}
                self.update_step(target_highlight=idx)
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss("Cancelled by user.")

    def action_minimize(self) -> None:
        self.dismiss({"action": "minimize", "answers": self.answers, "q_idx": self.q_idx})

    def action_go_back(self) -> None:
        if self.q_idx > 0:
            self.q_idx -= 1
            self.update_step()

    def action_go_next(self) -> None:
        """Right arrow: navigate to the next question; on the last one show/confirm summary."""
        if self.q_idx < len(self.questions):
            self.q_idx += 1
            self.update_step()
        else:
            self.submit_current_step()

    def _on_key(self, event: events.Key) -> None:
        norm_key = normalize_key_to_latin(event.key)
        if self.q_idx >= len(self.questions):
            if norm_key in ("up", "down", "pageup", "pagedown", "home", "end", "j", "k"):
                try:
                    scroll_box = self.query_one("#wizard-summary-scroll", ToolScrollBox)
                    if norm_key in ("up", "k"):
                        scroll_box.scroll_up(animate=False)
                    elif norm_key in ("down", "j"):
                        scroll_box.scroll_down(animate=False)
                    elif norm_key == "pageup":
                        scroll_box.scroll_page_up(animate=False)
                    elif norm_key == "pagedown":
                        scroll_box.scroll_page_down(animate=False)
                    elif norm_key == "home":
                        scroll_box.scroll_home(animate=False)
                    elif norm_key == "end":
                        scroll_box.scroll_end(animate=False)
                    event.prevent_default()
                    event.stop()
                    return
                except Exception:
                    pass
        if event.key in TAB_KEYS:
            self.action_toggle_selection()
            event.prevent_default()
            event.stop()
            return
