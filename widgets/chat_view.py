import asyncio
import difflib
import inspect
import json
import os
import re
import warnings
from typing import Any

import pygments
from markdown_it import MarkdownIt
from pygments.lexers import get_lexer_by_name
from pygments.token import Token
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.highlight import HighlightTheme
from textual.reactive import reactive
from textual.style import Style
from textual.widgets import Button, Label, Markdown, Static
from textual.widgets._markdown import MarkdownBlock, MarkdownFence

warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*await_update.*")


class CustomMarkdownFence(MarkdownFence):
    """Markdown code block with a header line and Copy button."""

    def compose(self) -> ComposeResult:
        lang_str = self.lexer.strip() if self.lexer else "code"
        copy_btn = Button("copy", classes="fence-copy-btn")
        copy_btn.can_focus = False
        with Horizontal(classes="fence-header"):
            yield Label(lang_str, classes="fence-lang")
            yield copy_btn
        yield Label(self._highlighted_code, id="code-content", expand=True)

    def set_content(self, content: Any) -> None:
        self._content = content
        try:
            self.query_one("#code-content", Label).update(content)
        except Exception:
            pass

    def render(self):
        return ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if "fence-copy-btn" in event.button.classes:
            try:
                app = self.app
                if hasattr(app, "copy_to_clipboard"):
                    app.copy_to_clipboard(self.code)
                    app.notify("Code block copied to clipboard!")
            except Exception:
                pass
            event.stop()


HighlightTheme.STYLES[Token.Name.Function] = "$text-warning"
HighlightTheme.STYLES[Token.Name.Function.Magic] = "$text-warning"

Markdown.BLOCKS["fence"] = CustomMarkdownFence
Markdown.BLOCKS["code_block"] = CustomMarkdownFence

def _custom_markdown_parser_factory() -> MarkdownIt:
    md = MarkdownIt("gfm-like")
    md.validateLink = lambda url: True
    return md



_old_markdown_init = Markdown.__init__
def _new_markdown_init(self, *args, **kwargs):
    if "parser_factory" not in kwargs or kwargs["parser_factory"] is None:
        kwargs["parser_factory"] = _custom_markdown_parser_factory
    _old_markdown_init(self, *args, **kwargs)
    self.BLOCKS["fence"] = CustomMarkdownFence
    self.BLOCKS["code_block"] = CustomMarkdownFence
Markdown.__init__ = _new_markdown_init


_old_markdown_block_get_style = MarkdownBlock._get_style
def _new_markdown_block_get_style(self, style):
    if style == ".code_inline":
        return Style(
            background=Color(39, 39, 42),
            foreground=Color(255, 255, 255),
        )
    return _old_markdown_block_get_style(self, style)
MarkdownBlock._get_style = _new_markdown_block_get_style




def safe_update_markdown(widget: Markdown, content: str) -> None:
    """Updates Markdown widget safely without creating unawaited coroutines when unattached."""
    if not getattr(widget, "is_attached", True):
        return
    try:
        res = widget.update(content)
        if inspect.isawaitable(res):
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(res)
            except RuntimeError:
                pass
    except Exception:
        pass


TOKEN_COLORS = {
    Token.Keyword: "bold #c678dd",
    Token.Keyword.Namespace: "bold #c678dd",
    Token.Keyword.Type: "#e5c07b",
    Token.Name.Function: "#61afef",
    Token.Name.Class: "#e5c07b",
    Token.Name.Builtin: "#e5c07b",
    Token.Name: "#f4f4f5",
    Token.String: "#98c379",
    Token.String.Doc: "#98c379",
    Token.Number: "#d19a66",
    Token.Operator: "#56b6c2",
    Token.Punctuation: "#abb2bf",
    Token.Comment: "#5c6370 italic",
}


class CompactionDivider(Static):
    """Full-width centered divider for session compaction"""
    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, title: str = "Session Compacted"):
        super().__init__(Rule(title, style="dim #71717a"), classes="compaction-divider")


class UserMessage(Static):
    """User message"""
    can_focus = False

    def __init__(self, content: str):
        self.raw_text = content
        super().__init__(content, classes="user-msg")


class BotMessage(Vertical):
    """AI message with full Markdown rendering"""
    can_focus = False
    content = reactive("")

    def __init__(self):
        super().__init__(classes="bot-msg")
        self.md_widget = Markdown("")
        self._update_scheduled = False

    def compose(self) -> ComposeResult:
        yield self.md_widget

    def watch_content(self, new_content: str) -> None:
        if not self._update_scheduled:
            self._update_scheduled = True
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(0.05, self._flush_update)
            except Exception:
                safe_update_markdown(self.md_widget, new_content)

    def _flush_update(self) -> None:
        self._update_scheduled = False
        safe_update_markdown(self.md_widget, self.content)


class ThinkingWidget(Vertical):
    """Thinking widget with Markdown expansion support"""
    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, thinking_text: str = ""):
        super().__init__(classes="thinking-widget thinking-active")
        self.thinking_text = "" if thinking_text == "Thinking..." else thinking_text
        self.duration_seconds = 0.0
        self.is_thinking = True
        self.is_expanded = False

        self.header_label = Label("Thinking...", classes="thinking-header")
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.md_widget

    def on_mount(self) -> None:
        self.md_widget.display = False

    def update_thinking(self, content: str) -> None:
        if content and content != "Thinking...":
            self.thinking_text = content
            if self.is_expanded:
                safe_update_markdown(self.md_widget, self.thinking_text)

    def finish_thinking(self, duration: float, thinking_content: str = "") -> None:
        self.is_thinking = False
        self.duration_seconds = duration
        if thinking_content and thinking_content != "Thinking...":
            self.thinking_text = thinking_content
        self.remove_class("thinking-active")
        if self.thinking_text and self.thinking_text != "Thinking...":
            safe_update_markdown(self.md_widget, self.thinking_text)
        else:
            safe_update_markdown(self.md_widget, "")
        self.render_collapsed()

    def render_collapsed(self) -> None:
        self.header_label.update(f"Thought for {self.duration_seconds:.1f} sec")
        if not self.is_expanded:
            self.md_widget.display = False

    def on_click(self, event) -> None:
        self.toggle_expanded()
        event.stop()

    def toggle_expanded(self) -> None:
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            if self.thinking_text:
                safe_update_markdown(self.md_widget, self.thinking_text)
            self.md_widget.display = True
        else:
            self.md_widget.display = False


class ToolCallWidget(Vertical):
    """Tool call widget (Create, Read, Edit, Bash) with expansion support"""
    can_focus = False
    ALLOW_SELECT = False

    EXPANDABLE_TOOLS = {
        "create", "edit", "bash", "read", "call_mcp_tool", "subagent", "task",
        "Create", "Edit", "Bash", "Read", "CallMCPTool", "Subagent", "Task"
    }

    def is_expandable(self) -> bool:
        return self.tool_type in self.EXPANDABLE_TOOLS

    def __init__(self, tool_type: str, target: str, result_text: str = "", is_sequential: bool = False, args: dict = None):
        classes = f"tool-call tool-{tool_type.lower()}"
        if is_sequential:
            classes += " tool-sequential"
        super().__init__(classes=classes)
        self.tool_type = tool_type
        if isinstance(target, str):
            import re
            target = re.sub(r'\s+', ' ', target.replace("\n", " ").replace("\r", " ")).strip()
        self.target = target
        self.result_text = result_text
        self.args = args or {}
        self.icon_name = tool_type
        self.is_expanded = False

        header_cls = "tool-header tool-header-expandable" if self.is_expandable() else "tool-header"
        self.header_label = Label("", classes=header_cls)
        self.content_widget = Static("", classes="tool-content")

    def _format_compact_dict(self, d: dict) -> str:
        if not isinstance(d, dict) or not d:
            return ""

        items = []
        total_len = 0
        overflow = False
        for k, v in d.items():
            k_str = str(k)
            if len(k_str) > 20:
                k_str = k_str[:17] + "..."

            if isinstance(v, str):
                v_clean = v.replace("\n", "\\n")
                if len(v_clean) > 35:
                    v_clean = v_clean[:32] + "..."
                v_str = f'"{v_clean}"'
            else:
                v_str = json.dumps(v, ensure_ascii=False)
                if len(v_str) > 35:
                    v_str = v_str[:32] + "..."

            item_str = f"{k_str}: {v_str}"
            if total_len + len(item_str) > 70:
                overflow = True
                break
            items.append(item_str)
            total_len += len(item_str) + 2

        if overflow and items:
            return "{" + ", ".join(items) + ", ...}"
        elif items:
            return "{" + ", ".join(items) + "}"
        else:
            return "{...}"

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.content_widget

    def on_mount(self) -> None:
        self.content_widget.display = False
        self.render_header()

    def set_result(self, result_text: str) -> None:
        cleaned = result_text.strip()
        if self.tool_type in ("bash", "Bash"):
            if "[Background Task ID:" in cleaned or "Command is running in the background" in cleaned:
                self.render_header()
                return
            if cleaned:
                self.result_text = cleaned
        else:
            self.result_text = cleaned
        self.render_header()
        if self.is_expanded:
            self.render_content()

    DISPLAY_NAMES = {
        "read": "Read",
        "create": "Create",
        "edit": "Edit",
        "bash": "Bash",
        "glob": "Glob",
        "grep": "Grep",
        "list_dir": "ListDir",
        "ask_user": "AskUser",
        "skill": "Skill",
        "manage_task": "ManageTask",
        "subagent": "Subagent",
        "manage_subagent": "ManageSubagent",
        "task": "Task",
        "view_image": "ViewImage",
        "call_mcp_tool": "CallMCPTool",
    }

    SYSTEM_TOOLS = {
        "read", "create", "edit", "bash", "glob", "grep", "list_dir",
        "ask_user", "skill", "manage_task", "manage_subagent",
        "subagent", "task", "view_image",
        "Read", "Create", "Edit", "Bash", "Glob", "Grep", "ListDir",
        "AskUser", "Skill", "ManageTask", "ManageSubagent",
        "Subagent", "Task", "ViewImage"
    }

    def render_header(self) -> None:
        if self.tool_type in self.SYSTEM_TOOLS or self.tool_type.lower() in ("subagent", "task"):
            display_name = self.DISPLAY_NAMES.get(self.tool_type.lower(), self.tool_type)
            self.header_label.update(f"⚙ [bold]{display_name}[/bold]({self.target})")
        elif self.tool_type in ("call_mcp_tool", "CallMCPTool"):
            tool_name = self.args.get("tool") or "call_mcp_tool"
            server = self.args.get("server") or ""
            mcp_args = self.args.get("arguments")
            if not isinstance(mcp_args, dict):
                mcp_args = {}

            compact = self._format_compact_dict(mcp_args)
            if not compact:
                compact = f"{{server: \"{server}\"}}" if server else "{}"
            escaped_compact = compact.replace("[", "\\[")
            self.header_label.update(f"⚙ [bold]{tool_name}[/bold]({escaped_compact})")
        else:
            # Eager MCP tool or custom external tool
            mcp_args = self.args if isinstance(self.args, dict) else {}
            compact = self._format_compact_dict(mcp_args)
            if compact:
                escaped_compact = compact.replace("[", "\\[")
                self.header_label.update(f"⚙ [bold]{self.tool_type}[/bold]({escaped_compact})")
            else:
                display_name = self.DISPLAY_NAMES.get(self.tool_type.lower(), self.tool_type)
                self.header_label.update(f"⚙ [bold]{display_name}[/bold]({self.target})")

    def on_click(self, event) -> None:
        if self.tool_type.lower() in ("subagent", "task"):
            task_id = self.args.get("task_id") if isinstance(self.args, dict) else None
            identifier = task_id or self.target
            try:
                from widgets.screens.subagent_screen import SubagentViewScreen
                self.app.push_screen(SubagentViewScreen(identifier))
            except Exception:
                pass
            event.stop()
            return

        if self.is_expandable():
            self.toggle_expanded()
            event.stop()

    def toggle_expanded(self) -> None:
        if not self.is_expandable():
            return
        self.is_expanded = not self.is_expanded
        self.render_header()
        if self.is_expanded:
            self.render_content()
            self.content_widget.display = True
        else:
            self.content_widget.display = False

    def _guess_lexer(self, path_str: str) -> str:
        if not path_str:
            return "text"
        ext = os.path.splitext(path_str)[1].lower().lstrip(".")
        mapping = {
            "py": "python",
            "js": "javascript",
            "jsx": "jsx",
            "ts": "typescript",
            "tsx": "tsx",
            "html": "html",
            "css": "css",
            "scss": "scss",
            "json": "json",
            "yaml": "yaml",
            "yml": "yaml",
            "md": "markdown",
            "sh": "bash",
            "bash": "bash",
            "zsh": "bash",
            "rs": "rust",
            "go": "go",
            "c": "c",
            "cpp": "cpp",
            "h": "c",
            "hpp": "cpp",
            "sql": "sql",
            "toml": "toml",
            "ini": "ini",
            "dockerfile": "dockerfile",
            "xml": "xml"
        }
        return mapping.get(ext, ext or "text")

    def _lex_block_to_line_texts(self, code_lines: list[str], lexer: Any) -> list[Text]:
        if not code_lines:
            return []
        if not lexer:
            return [Text(line) for line in code_lines]

        full_code = "\n".join(code_lines)
        try:
            tokens = pygments.lex(full_code, lexer)
            line_texts = [Text()]
            for tok_type, val in tokens:
                parts = val.split("\n")
                for idx, part in enumerate(parts):
                    if idx > 0:
                        line_texts.append(Text())
                    if part:
                        style = None
                        curr = tok_type
                        while curr:
                            if curr in TOKEN_COLORS:
                                style = TOKEN_COLORS[curr]
                                break
                            curr = curr.parent
                        line_texts[-1].append(part, style=style)

            while len(line_texts) < len(code_lines):
                line_texts.append(Text())
            return line_texts[:len(code_lines)]
        except Exception:
            return [Text(line) for line in code_lines]

    def _format_edit_diff(self, diff_text: str, file_path: str) -> Text:
        if "[Linter Feedback]:" in diff_text:
            diff_text = diff_text.split("[Linter Feedback]:")[0].strip()

        lexer_name = self._guess_lexer(file_path)
        try:
            lexer = get_lexer_by_name(lexer_name)
        except Exception:
            lexer = None

        lines = diff_text.splitlines()
        formatted_lines = []

        old_code_lines = []
        new_code_lines = []
        in_hunk = False
        for line in lines:
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            if re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line):
                in_hunk = True
                continue
            if not in_hunk:
                continue

            if line.startswith("-"):
                old_code_lines.append(line[1:])
            elif line.startswith("+"):
                new_code_lines.append(line[1:])
            elif line.startswith(" "):
                old_code_lines.append(line[1:])
                new_code_lines.append(line[1:])

        old_texts = self._lex_block_to_line_texts(old_code_lines, lexer)
        new_texts = self._lex_block_to_line_texts(new_code_lines, lexer)

        old_line = 0
        new_line = 0
        old_idx = 0
        new_idx = 0
        in_hunk = False

        max_num_digits = 3
        for line in lines:
            h_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if h_match:
                o_val = int(h_match.group(1))
                n_val = int(h_match.group(2))
                max_num_digits = max(max_num_digits, len(str(o_val + 20)), len(str(n_val + 20)))

        width = 120
        try:
            if self.app and self.app.console:
                width = max(self.app.console.width, 100)
        except Exception:
            pass

        for idx, line in enumerate(lines):
            if line.startswith("--- ") or line.startswith("+++ "):
                continue

            hunk_match = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if hunk_match:
                old_line = int(hunk_match.group(1))
                new_line = int(hunk_match.group(2))
                in_hunk = True
                continue

            if not in_hunk:
                if line.strip():
                    formatted_lines.append(Text(line, style="dim"))
                continue

            if line.startswith("-"):
                num_str = str(old_line).rjust(max_num_digits)
                prefix = Text(f"{num_str} - ", style="bold #f87171 on #2c1517")
                code_text = old_texts[old_idx] if old_idx < len(old_texts) else Text(line[1:])
                old_idx += 1
                full_line = prefix + code_text
                full_line.pad_right(width)
                full_line.stylize("on #2c1517")
                formatted_lines.append(full_line)
                old_line += 1
            elif line.startswith("+"):
                num_str = str(new_line).rjust(max_num_digits)
                prefix = Text(f"{num_str} + ", style="bold #4ade80 on #132e22")
                code_text = new_texts[new_idx] if new_idx < len(new_texts) else Text(line[1:])
                new_idx += 1
                full_line = prefix + code_text
                full_line.pad_right(width)
                full_line.stylize("on #132e22")
                formatted_lines.append(full_line)
                new_line += 1
            elif line.startswith(" "):
                num_str = str(new_line).rjust(max_num_digits)
                prefix = Text(f"{num_str}   ", style="dim #71717a")
                code_text = new_texts[new_idx] if new_idx < len(new_texts) else Text(line[1:])
                old_idx += 1
                new_idx += 1
                full_line = prefix + code_text
                formatted_lines.append(full_line)
                old_line += 1
                new_line += 1
            elif line.startswith("\\"):
                formatted_lines.append(Text(line, style="dim"))
            else:
                formatted_lines.append(Text(line, style="dim"))
                in_hunk = False

        return Text("\n").join(formatted_lines)

    def _format_read_content(self, text: str, default_file_path: str) -> tuple[str, int, str]:
        lines = text.splitlines()
        if not lines:
            return "", 1, default_file_path

        start_line = 1
        file_path = default_file_path

        header_match = re.match(r"^===\s+Lines\s+(\d+)-\d+\s+of\s+\d+\s+in\s+([^\s=]+)", lines[0])
        if header_match:
            start_line = int(header_match.group(1))
            file_path = header_match.group(2)
            lines = lines[1:]

        clean_code_lines = []
        for line in lines:
            cleaned_line = re.sub(r"^\s*\d+\s*\|\s?", "", line)
            clean_code_lines.append(cleaned_line)

        return "\n".join(clean_code_lines), start_line, file_path

    def _clean_bash_output(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"\[Background Task ID:[^\]]+\][^\[\n]*", "", text)
        cleaned = re.sub(r"Command is running in the background[^\n]*", "", cleaned)
        cleaned = re.sub(r"You will be notified automatically[^\n]*", "", cleaned)
        cleaned = re.sub(r"Use (manage_task|ManageTask) to inspect[^\n]*", "", cleaned)
        return cleaned.strip()

    def append_bash_output(self, text: str) -> None:
        cleaned_line = self._clean_bash_output(text)
        if not cleaned_line:
            return
        if not self.result_text:
            self.result_text = cleaned_line
        else:
            sep = "" if self.result_text.endswith("\n") else "\n"
            self.result_text += sep + cleaned_line
        if self.is_expanded:
            self.render_content()

    def render_content(self) -> None:
        try:
            file_path = self.args.get("path") or self.args.get("file") or self.target
            if self.tool_type in ("create", "Create"):
                content = self.args.get("content")
                if content is None:
                    if file_path and os.path.isfile(file_path):
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                                content = f.read()
                        except Exception:
                            content = None

                if content is not None:
                    lexer = self._guess_lexer(file_path)
                    try:
                        syntax = Syntax(
                            content,
                            lexer,
                            theme="one-dark",
                            line_numbers=True,
                            word_wrap=True,
                            background_color="#18181b"
                        )
                        self.content_widget.update(syntax)
                    except Exception:
                        rendered = self._format_code_with_line_numbers(content)
                        self.content_widget.update(rendered)
                else:
                    self.content_widget.update(self.result_text or "(No content)")
            elif self.tool_type in ("edit", "Edit"):
                diff_text = self.result_text.strip()
                if not diff_text or "@@" not in diff_text:
                    old_s = self.args.get("old_string", "")
                    new_s = self.args.get("new_string", "")
                    if old_s or new_s:
                        diff_lines = list(difflib.unified_diff(
                            old_s.splitlines(),
                            new_s.splitlines(),
                            fromfile=file_path,
                            tofile=file_path,
                            lineterm=""
                        ))
                        diff_text = "\n".join(diff_lines)

                if diff_text:
                    formatted_diff = self._format_edit_diff(diff_text, file_path)
                    self.content_widget.update(formatted_diff)
                else:
                    self.content_widget.update(self.result_text or "(No diff)")
            elif self.tool_type in ("read", "Read"):
                raw_text = self.result_text
                clean_code, start_line, fpath = self._format_read_content(raw_text, file_path)
                if not clean_code.strip() and fpath and os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            clean_code = f.read()
                            start_line = 1
                    except Exception:
                        clean_code = ""

                if clean_code:
                    lexer = self._guess_lexer(fpath)
                    try:
                        syntax = Syntax(
                            clean_code,
                            lexer,
                            theme="one-dark",
                            line_numbers=True,
                            start_line=start_line,
                            word_wrap=True,
                            background_color="#18181b"
                        )
                        self.content_widget.update(syntax)
                    except Exception:
                        rendered = self._format_code_with_line_numbers(clean_code)
                        self.content_widget.update(rendered)
                else:
                    self.content_widget.update(self.result_text or "(No content)")
            elif self.tool_type in ("bash", "Bash"):
                output_text = self._clean_bash_output(self.result_text)
                if not output_text.strip():
                    output_text = "(Running command...)"
                self.content_widget.update(output_text)
            elif self.tool_type in ("call_mcp_tool", "CallMCPTool"):
                server = self.args.get("server", "")
                tool = self.args.get("tool", "")
                mcp_args = self.args.get("arguments", {})
                display_parts = [f"Server: {server}", f"Tool: {tool}"]
                if mcp_args:
                    try:
                        args_json = json.dumps(mcp_args, indent=2, ensure_ascii=False)
                        display_parts.append(f"Arguments:\n{args_json}")
                    except Exception:
                        display_parts.append(f"Arguments: {mcp_args}")
                if self.result_text:
                    display_parts.append(f"\nResult:\n{self.result_text.strip()}")
                full_display = "\n".join(display_parts)
                try:
                    syntax = Syntax(
                        full_display,
                        "json",
                        theme="one-dark",
                        word_wrap=True,
                        background_color="#18181b"
                    )
                    self.content_widget.update(syntax)
                except Exception:
                    self.content_widget.update(full_display)
            else:
                self.content_widget.update(self.result_text or "(No result)")
        except Exception:
            pass

    def _format_code_with_line_numbers(self, code: str) -> str:
        lines = code.splitlines()
        if not lines:
            return "[dim]1 │ [/dim]"
        max_digits = max(len(str(len(lines))), 2)
        formatted = []
        for i, line in enumerate(lines, 1):
            num_str = str(i).rjust(max_digits)
            escaped_line = line.replace("[", "\\[")
            formatted.append(f"[dim]{num_str} │ [/dim]{escaped_line}")
        return "\n".join(formatted)


class WelcomeWidget(Vertical):
    """Centered welcome logo on main screen"""
    can_focus = False

    FULL_BANNER = (
        "   _       _                 _                 \n"
        "  (_)     | |               | |                \n"
        "   _  ___ | |__  _ __  ___ _| |_ ___  _ __     \n"
        "  | |/ _ \\| '_ \\| '_ \\/ __|_   _/ _ \\| '_ \\    \n"
        "  | | (_) | | | | | | \\__ \\ | || (_) | | | |   \n"
        "  | |\\___/|_| |_|_| |_|___/  \\__\\___/|_| |_|   \n"
        " /_/                                           "
    )

    def compose(self) -> ComposeResult:
        yield Static(self.FULL_BANNER, id="welcome-logo")

    def _update_banner_for_size(self, width: int) -> None:
        try:
            logo = self.query_one("#welcome-logo", Static)
            if width < 52:
                logo.update("[bold #ffffff]johnston[/bold #ffffff]")
            else:
                logo.update(self.FULL_BANNER)
        except Exception:
            pass

    def on_mount(self) -> None:
        if self.app and self.app.size.width > 0:
            self._update_banner_for_size(self.app.size.width)

    def on_resize(self, event) -> None:
        self._update_banner_for_size(event.size.width)


class ChatView(VerticalScroll):
    """Scrollable chat stream"""
    can_focus = False

    def __init__(self, *args, show_welcome: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_welcome = show_welcome

    def on_mount(self) -> None:
        self.check_welcome()

    def clear_welcome(self) -> None:
        for w in self.query(WelcomeWidget):
            w.remove()

    def check_welcome(self) -> None:
        if not getattr(self, "show_welcome", True):
            self.clear_welcome()
            return
        msg_children = [c for c in self.children if not isinstance(c, WelcomeWidget)]
        welcome = list(self.query(WelcomeWidget))
        if not msg_children:
            if not welcome:
                self.mount(WelcomeWidget())
        else:
            for w in welcome:
                w.remove()

    async def add_user_message(self, text: str) -> UserMessage:
        self.clear_welcome()
        msg = UserMessage(text)
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_bot_message(self) -> BotMessage:
        self.clear_welcome()
        msg = BotMessage()
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_thinking_widget(self, thinking_text: str = "Thinking...") -> ThinkingWidget:
        self.clear_welcome()
        widget = ThinkingWidget(thinking_text)
        await self.mount(widget)
        self.scroll_end(animate=True)
        return widget

    async def add_tool_call(self, tool_type: str, target: str, result_text: str = "", args: dict = None) -> ToolCallWidget:
        self.clear_welcome()
        is_seq = bool(self.children and isinstance(self.children[-1], ToolCallWidget))
        widget = ToolCallWidget(tool_type, target, result_text=result_text, is_sequential=is_seq, args=args)
        await self.mount(widget)
        self.scroll_end(animate=True)
        return widget

    async def add_compaction_divider(self, text: str = "Session Compacted") -> CompactionDivider:
        self.clear_welcome()
        widget = CompactionDivider(text)
        await self.mount(widget)
        self.scroll_end(animate=True)
        return widget

    def get_user_messages(self) -> list[tuple[int, str]]:
        result = []
        for idx, child in enumerate(self.children):
            if isinstance(child, UserMessage):
                result.append((idx, child.raw_text))
        return result

    def rollback_to(self, target_index: int) -> None:
        children = list(self.children)
        start_idx = max(0, target_index + 1)
        for child in children[start_idx:]:
            child.remove()
        self.check_welcome()
