import os

from textual.widgets import OptionList

from commands import COMMAND_REGISTRY
from core.skill_manager import SkillManager


def get_all_command_suggestions() -> list[tuple[str, str]]:
    """Gets list of (command_name, description) for registered commands and skills"""
    suggestions = []
    registered = set()

    for name, cmd in COMMAND_REGISTRY.items():
        desc = cmd.description if name == cmd.name else f"Alias for {cmd.name}"
        suggestions.append((name, desc))
        registered.add(name)

    try:
        sm = SkillManager()
        skills = sm.list_skills()
        for s in skills:
            s_cmd = f"/{s['name']}"
            if s_cmd not in registered:
                desc = f"Skill: {s['description']}" if s.get("description") else f"Skill: {s['name']}"
                suggestions.append((s_cmd, desc))
                registered.add(s_cmd)
    except Exception:
        pass

    return suggestions


class CommandSuggestions(OptionList):
    """Dropdown suggestions menu for slash commands (/help, /rewind) and file attachments (@file)"""

    can_focus = False
    ALLOW_SELECT = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode: str | None = None  # "command" or "file"
        self.current_matched: list[str] = []
        self.at_start_idx: int = -1

    def get_workspace_files(self) -> list[str]:
        """Gets relative file paths list in current project"""
        files_list = []
        cwd = os.getcwd()
        ignore_dirs = {
            ".git", ".venv", "venv", "__pycache__", ".johnston",
            "node_modules", ".mypy_cache", ".pytest_cache", ".idea",
            ".vscode", "build", "dist", ".gemini", ".next", ".cache"
        }
        try:
            for root, dirs, files in os.walk(cwd):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                rel_dir = os.path.relpath(root, cwd)
                for f in files:
                    if f.startswith(".") or f.endswith(".pyc"):
                        continue
                    rel_path = f if rel_dir == "." else os.path.join(rel_dir, f)
                    files_list.append(rel_path.replace("\\", "/"))
                    if len(files_list) >= 1000:
                        break
                if len(files_list) >= 1000:
                    break
        except Exception:
            pass
        return sorted(files_list)

    def update_query(self, full_text: str, current_line: str = "", cursor_col: int | None = None) -> list[str]:
        """Updates matches list formatted for /commands and @files"""
        self.clear_options()
        self.mode = None
        self.current_matched = []
        self.at_start_idx = -1

        if not full_text:
            self.display = False
            return []

        # 1. Check for slash command at start of input
        cleaned = full_text.strip().lower()
        if cleaned.startswith("/") and " " not in cleaned:
            self.mode = "command"
            matched_cmds = []
            all_cmds = get_all_command_suggestions()
            max_cmd_len = max((len(c) for c, _ in all_cmds), default=14)
            padding = max(16, max_cmd_len + 2)
            for cmd, desc in all_cmds:
                if cmd.startswith(cleaned):
                    matched_cmds.append(cmd)
                    clean_desc = " ".join(desc.split())
                    if len(clean_desc) > 60:
                        clean_desc = clean_desc[:57] + "..."
                    formatted_line = f"{cmd:<{padding}} {clean_desc}"
                    self.add_option(formatted_line)

            self.current_matched = matched_cmds
            if matched_cmds:
                self.display = True
                self.highlighted = 0
            else:
                self.display = False
            return matched_cmds

        # 2. Check for @file input
        check_text = current_line[:cursor_col] if cursor_col is not None else current_line or full_text
        at_idx = check_text.rfind("@")
        if at_idx != -1:
            if at_idx == 0 or check_text[at_idx - 1] in " \t\n":
                query_part = check_text[at_idx + 1:]
                if " " not in query_part and "\n" not in query_part:
                    self.mode = "file"
                    self.at_start_idx = at_idx
                    query_lower = query_part.lower()
                    files = self.get_workspace_files()
                    matched_files = []
                    for f in files:
                        if not query_lower or query_lower in f.lower():
                            matched_files.append(f)
                            formatted_line = f"{f:<46} File"
                            self.add_option(formatted_line)
                            if len(matched_files) >= 50:
                                break

                    self.current_matched = matched_files
                    if matched_files:
                        self.display = True
                        self.highlighted = 0
                    else:
                        self.display = False
                    return matched_files

        self.display = False
        return []

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Mouse click on suggestion option"""
        event.stop()
        if not self.app or not self.current_matched or self.highlighted is None:
            return
        if self.highlighted < len(self.current_matched):
            try:
                from widgets.chat_input import ChatInput
                chat_input = self.app.query_one("#message-input", ChatInput)
                if self.mode == "command":
                    chosen_cmd = self.current_matched[self.highlighted]
                    chat_input.load_text(chosen_cmd + " ")
                    lines = chat_input.text.split("\n")
                    chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
                elif self.mode == "file":
                    chosen_file = self.current_matched[self.highlighted]
                    chat_input.apply_file_suggestion(chosen_file, self.at_start_idx)
                self.display = False
                chat_input.focus()
            except Exception:
                pass

