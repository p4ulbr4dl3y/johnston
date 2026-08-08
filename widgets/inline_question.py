from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

DEMO_QUESTIONS = [
    {
        "question_text": "Что хочешь сделать с этим багом?",
        "options": [
            "(Recommended) Починить сразу",
            "Сначала написать тест",
            "Только посмотреть код",
            "Отложить до завтра",
        ],
    },
    {
        "question_text": "Какие файлы задействовать?",
        "options": [
            "core/session_manager.py",
            "widgets/chat_input.py",
            "widgets/status_footer.py",
            "app.py",
        ],
    },
    {
        "question_text": "Опиши подробности свободным текстом:",
        "options": [],
    },
]


class WriteInInput(Input):
    """Custom Input widget that handles Up key to return focus to OptionList and prevents select-all"""

    def _clear_selection(self) -> None:
        val_len = len(self.value)
        self.cursor_position = val_len
        try:
            from textual.widgets._input import Selection

            self.selection = Selection(val_len, val_len)
        except Exception:
            try:
                self.selection = (val_len, val_len)
            except Exception:
                pass

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        self._clear_selection()
        self.call_after_refresh(self._clear_selection)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.parent and hasattr(self.parent, "save_write_in_draft"):
            getattr(self.parent, "save_write_in_draft")(event.value)

    def _on_input(self, event: Input.Changed) -> None:
        self.on_input_changed(event)

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        cursor = self.cursor_position
        val_len = len(self.value)

        if key in ("up", "key_up"):
            if self.parent and getattr(self.parent, "raw_options", None):
                if hasattr(self.parent, "focus_options_list"):
                    getattr(self.parent, "focus_options_list")()
                    event.stop()
                    event.prevent_default()
                    return
            else:
                if self.parent and hasattr(self.parent, "action_go_back"):
                    getattr(self.parent, "action_go_back")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("left", "key_left"):
            if cursor == 0:
                if self.parent and hasattr(self.parent, "action_go_back"):
                    getattr(self.parent, "action_go_back")()
                    event.stop()
                    event.prevent_default()
                    return

        elif key in ("right", "key_right"):
            if cursor == val_len:
                if self.parent and hasattr(self.parent, "action_go_next"):
                    getattr(self.parent, "action_go_next")()
                    event.stop()
                    event.prevent_default()
                    return

        await super()._on_key(event)


class QuestionOptionList(OptionList):
    """Custom OptionList that intercepts Space to toggle selection without advancing."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "space":
            if self.parent and hasattr(self.parent, "action_toggle_selection"):
                getattr(self.parent, "action_toggle_selection")()
                event.stop()
                event.prevent_default()
                return
        await super()._on_key(event)


class InlineQuestionBar(Vertical):
    """Widget mounted in place of ChatInput & StatusFooter matching AskUserWizardScreen bindings 1-in-1."""

    can_focus = True

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "go_back", "Back"),
        Binding("right", "go_next", "Next"),
        Binding("enter", "go_next", "Next / Confirm"),
        Binding("space", "toggle_selection", "Toggle Selection"),
    ]

    DEFAULT_CSS = """
    InlineQuestionBar {
        width: 100%;
        height: auto;
        max-height: 14;
        overflow-y: auto;
        background: #18181b;
        border-top: double #27272a;
        padding: 1 2 0 2;
        margin: 0;
    }

    InlineQuestionBar #wizard-title {
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
    }

    InlineQuestionBar #wizard-title MarkdownParagraph {
        color: #e4e4e7;
        margin: 0;
    }

    InlineQuestionBar #wizard-title MarkdownEm,
    InlineQuestionBar #wizard-title MarkdownEmphasis {
        color: #a1a1aa;
        text-style: none;
    }

    InlineQuestionBar OptionList,
    InlineQuestionBar OptionList:focus {
        height: auto;
        max-height: 7;
        margin: 0 0 1 0;
        border: none;
        background: #27272a;
        scrollbar-size: 0 0;
    }

    InlineQuestionBar OptionList > .option-list--option-highlighted,
    InlineQuestionBar OptionList > .option-list--option-blur-highlighted {
        background: #ffffff;
        color: #09090b;
        text-style: bold;
    }

    InlineQuestionBar WriteInInput {
        margin: 0 0 1 0;
        background: #09090b;
        border: solid #27272a;
        color: #f4f4f5;
        height: 3;
    }

    InlineQuestionBar WriteInInput:focus {
        border: solid #52525b;
    }

    InlineQuestionBar #modal-hint {
        height: 1;
        color: #71717a;
        text-align: center;
        margin: 1 0 1 0;
    }
    """

    def __init__(self, questions: list[dict] | None = None, callback=None):
        super().__init__(id="inline-question-bar")
        self.questions = questions or DEMO_QUESTIONS
        self.answers = {}
        self.write_in_drafts = {}
        self.q_idx = 0
        self.callback = callback
        self.raw_options = []
        self.options = []

    def compose(self) -> ComposeResult:
        yield Markdown("", id="wizard-title", classes="modal-markdown")
        yield QuestionOptionList(id="options-list")
        yield WriteInInput(placeholder="Type response here and press Enter...", id="write-in-input")
        yield Label("", id="modal-hint")

    def on_mount(self) -> None:
        self.update_step()
        self.call_after_refresh(self._force_focus)
        self.set_timer(0.05, self._force_focus)
        self.set_timer(0.15, self._force_focus)
        self.set_timer(0.30, self._force_focus)

    def on_focus(self, event: events.Focus) -> None:
        self._force_focus()

    def _force_focus(self) -> None:
        if not self.is_mounted:
            return
        if self.q_idx < len(self.questions):
            if self.raw_options:
                try:
                    self.query_one("#options-list", QuestionOptionList).focus()
                except Exception:
                    pass
            else:
                try:
                    self.query_one("#write-in-input", WriteInInput).focus()
                except Exception:
                    pass

    def save_write_in_draft(self, val: str) -> None:
        if self.q_idx < len(self.questions):
            self.write_in_drafts[self.q_idx] = val

    def update_step(self, target_highlight: int | None = None) -> None:
        title_md = self.query_one("#wizard-title", Markdown)
        opt_list = self.query_one("#options-list", OptionList)
        input_field = self.query_one("#write-in-input", WriteInInput)
        hint = self.query_one("#modal-hint", Label)

        if self.q_idx < len(self.questions):
            q = self.questions[self.q_idx]
            if isinstance(q, str):
                q_text = q
                self.raw_options = []
            elif isinstance(q, dict):
                q_text = str(q.get("question_text") or q.get("question") or "").strip()
                self.raw_options = q.get("options") or []
            else:
                q_text = str(q)
                self.raw_options = []

            title_md.update(f"### **Question {self.q_idx + 1}/{len(self.questions)}**\n{q_text}")
            hint.update("enter: confirm • space: toggle • ←: back • →: next • esc: cancel")

            self.options = self.raw_options + ["Write-in..."] if self.raw_options else []
            prev_raw = self.answers.get(self.q_idx, {})
            if isinstance(prev_raw, dict):
                prev_answer = prev_raw.get("answer", "")
            else:
                prev_answer = str(prev_raw or "")

            draft_val = self.write_in_drafts.get(self.q_idx, prev_answer)

            if self.raw_options:
                opt_list.display = True
                opt_list.clear_options()

                if target_highlight is not None and target_highlight < len(self.options):
                    highlight_idx = target_highlight
                    if highlight_idx == len(self.options) - 1 and draft_val and draft_val not in self.raw_options:
                        input_field.value = draft_val
                    elif highlight_idx < len(self.raw_options):
                        input_field.value = draft_val
                elif prev_answer:
                    if prev_answer in self.raw_options:
                        highlight_idx = self.raw_options.index(prev_answer)
                        input_field.value = draft_val
                    else:
                        highlight_idx = len(self.options) - 1
                        input_field.value = draft_val
                        input_field.display = True
                else:
                    highlight_idx = 0
                    input_field.value = draft_val

                for idx, opt in enumerate(self.options):
                    is_selected = bool(
                        prev_answer
                        and (
                            (idx < len(self.raw_options) and prev_answer == self.raw_options[idx])
                            or (idx == len(self.options) - 1 and prev_answer not in self.raw_options)
                        )
                    )
                    tag = r"\[✓]" if is_selected else r"\[ ]"
                    opt_list.add_option(f"{tag} {opt}")

                opt_list.highlighted = highlight_idx
                if highlight_idx == len(self.options) - 1:
                    self.focus_write_in_input()
                else:
                    input_field.display = False
                    opt_list.focus()
            else:
                opt_list.display = False
                input_field.display = True
                input_field.value = draft_val
                input_field.focus()
        else:
            blocks = []
            for idx, q in enumerate(self.questions):
                if isinstance(q, str):
                    q_clean = q
                elif isinstance(q, dict):
                    q_clean = str(q.get("question_text") or q.get("question") or "").strip()
                else:
                    q_clean = str(q)

                ans_info = self.answers.get(idx, {})
                if isinstance(ans_info, dict):
                    ans_val = ans_info.get("answer", "")
                else:
                    ans_val = str(ans_info or "")

                ans_display = ans_val if ans_val else "(No response)"
                blocks.append(f"- **{q_clean}** → {ans_display}")

            summary = "\n".join(blocks)
            title_md.update("### **Confirm Your Answers**\n\n" + summary)
            opt_list.display = False
            input_field.display = False
            hint.update("enter: confirm • esc: cancel")
            self.focus()

    def focus_write_in_input(self) -> None:
        try:
            input_field = self.query_one("#write-in-input", WriteInInput)
            input_field.display = True
            self.call_after_refresh(input_field.focus)
        except Exception:
            pass

    def focus_options_list(self) -> None:
        if not self.raw_options:
            return
        try:
            input_field = self.query_one("#write-in-input", WriteInInput)
            opt_list = self.query_one("#options-list", QuestionOptionList)
            input_field.display = False
            opt_list.highlighted = max(0, len(self.options) - 2)
            self.call_after_refresh(opt_list.focus)
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted or not self.raw_options or self.q_idx >= len(self.questions):
            return
        try:
            input_field = self.query_one("#write-in-input", WriteInInput)
            if event.option_index == len(self.options) - 1:
                self.focus_write_in_input()
            else:
                input_field.display = False
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.raw_options or self.q_idx >= len(self.questions):
            return
        if event.option_index != len(self.options) - 1:
            self.submit_current_step()
        else:
            self.focus_write_in_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submit_current_step()

    def submit_current_step(self) -> None:
        if self.q_idx < len(self.questions):
            if not self.raw_options:
                val = self.query_one("#write-in-input", WriteInInput).value.strip()
                answer = val
            else:
                opt_list = self.query_one("#options-list", OptionList)
                idx = opt_list.highlighted
                if idx == len(self.options) - 1:
                    val = self.query_one("#write-in-input", WriteInInput).value.strip()
                    answer = val
                else:
                    answer = self.raw_options[idx] if idx is not None and idx < len(self.raw_options) else ""

            self.answers[self.q_idx] = {"answer": answer}
            self.q_idx += 1
            self.update_step()

    def action_toggle_selection(self) -> None:
        if not self.raw_options or self.q_idx >= len(self.questions):
            return
        try:
            opt_list = self.query_one("#options-list", OptionList)
            if not opt_list.has_focus:
                return
            idx = opt_list.highlighted
            if idx is not None and idx < len(self.raw_options):
                chosen = self.raw_options[idx]
                current_ans = self.answers.get(self.q_idx, {}).get("answer", "")
                if current_ans == chosen:
                    self.answers[self.q_idx] = {"answer": ""}
                else:
                    self.answers[self.q_idx] = {"answer": chosen}
                self.update_step(target_highlight=idx)
        except Exception:
            pass

    def action_go_next(self) -> None:
        if self.q_idx < len(self.questions):
            self.q_idx += 1
            self.update_step()
        else:
            self.finish(cancelled=False)

    def action_go_back(self) -> None:
        if self.q_idx > 0:
            self.q_idx -= 1
            self.update_step()

    def action_cancel(self) -> None:
        self.finish(cancelled=True)

    def finish(self, cancelled: bool = False) -> None:
        if self.callback:
            if cancelled:
                res = None
            else:
                res = {}
                for idx, a in self.answers.items():
                    if isinstance(a, dict):
                        res[idx] = a.get("answer", "")
                    else:
                        res[idx] = str(a or "")
            self.callback(res)
        self.remove()
