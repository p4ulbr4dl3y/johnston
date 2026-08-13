import os
import time

from textual.widgets import OptionList

from core.skill_manager import SkillManager
from widgets.commands import COMMAND_REGISTRY

_command_suggestions_cache: list[tuple[str, str]] = []
_command_suggestions_cache_time: float = 0.0


def get_all_command_suggestions() -> list[tuple[str, str]]:
    """Gets list of (command_name, description) for registered commands and skills with 10s cache"""
    global _command_suggestions_cache, _command_suggestions_cache_time
    now = time.time()
    if _command_suggestions_cache and (now - _command_suggestions_cache_time < 10.0):
        return _command_suggestions_cache

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

    _command_suggestions_cache = suggestions
    _command_suggestions_cache_time = now
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
        self._cached_files: list[str] = []
        self._cache_time: float = 0.0

    def get_workspace_files(self) -> list[str]:
        """Gets relative file paths list in current project with 5s caching"""
        now = time.time()
        if self._cached_files and (now - self._cache_time < 30.0):
            return self._cached_files

        files_list = []
        cwd = os.getcwd()
        real_cwd = os.path.realpath(cwd)
        home = os.path.realpath(os.path.expanduser("~"))

        is_home_or_root = real_cwd == home or os.path.dirname(real_cwd) == real_cwd
        max_files = 300 if is_home_or_root else 1000

        from core.defaults.git_excludes import DEFAULT_IGNORE_DIRS

        ignore_dirs = DEFAULT_IGNORE_DIRS | {
            ".idea",
            ".vscode",
            ".gemini",
            ".cache",
            "Library",
            ".Trash",
            "Applications",
            "Pictures",
            "Movies",
            "Music",
        }
        try:
            for root, dirs, files in os.walk(cwd):
                rel_dir = os.path.relpath(root, cwd)
                depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
                if is_home_or_root and depth >= 2:
                    dirs.clear()
                    continue
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                for d in dirs:
                    rel_path = d if rel_dir == "." else os.path.join(rel_dir, d)
                    files_list.append(rel_path.replace("\\", "/") + "/")
                    if len(files_list) >= max_files:
                        break
                for f in files:
                    if f.startswith(".") or f.endswith(".pyc"):
                        continue
                    rel_path = f if rel_dir == "." else os.path.join(rel_dir, f)
                    files_list.append(rel_path.replace("\\", "/"))
                    if len(files_list) >= max_files:
                        break
                if len(files_list) >= max_files:
                    break
        except Exception:
            pass
        self._cached_files = sorted(set(files_list))
        self._cache_time = now
        return self._cached_files

    def update_query(self, full_text: str, current_line: str = "", cursor_col: int | None = None) -> list[str]:
        """Updates matches list formatted for /commands and @files"""
        check_text = current_line[:cursor_col] if cursor_col is not None else current_line or full_text

        # 1. Check for slash command at any position (/command or /skill)
        slash_idx = check_text.rfind("/")
        if slash_idx != -1:
            if slash_idx == 0 or check_text[slash_idx - 1] in " \t\n":
                query_part = check_text[slash_idx:]
                if " " not in query_part and "\n" not in query_part:
                    self.clear_options()
                    self.mode = "command"
                    self.at_start_idx = slash_idx
                    query_lower = query_part.lower()
                    matched_cmds = []
                    all_cmds = get_all_command_suggestions()
                    max_cmd_len = max((len(c) for c, _ in all_cmds), default=14)
                    padding = max(16, max_cmd_len + 2)
                    for cmd, desc in all_cmds:
                        if cmd.lower().startswith(query_lower):
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
        at_idx = check_text.rfind("@")
        if at_idx != -1:
            if at_idx == 0 or check_text[at_idx - 1] in " \t\n":
                query_part = check_text[at_idx + 1 :]
                if " " not in query_part and "\n" not in query_part:
                    self.clear_options()
                    self.mode = "file"
                    self.at_start_idx = at_idx
                    query_lower = query_part.lower()
                    files = self.get_workspace_files()
                    matched_files = []
                    seen: set[str] = set()
                    for f in files:
                        if f in seen:
                            continue
                        seen.add(f)
                        if not query_lower or query_lower in f.lower():
                            matched_files.append(f)
                            kind = "Dir" if f.endswith("/") else "File"
                            formatted_line = f"{f:<46} {kind}"
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

        if self.mode is not None or self.display or self.option_count:
            self.clear_options()
            self.display = False
        self.mode = None
        self.current_matched = []
        self.at_start_idx = -1
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
                    chat_input.apply_suggestion(chosen_cmd, self.at_start_idx)
                elif self.mode == "file":
                    chosen_file = self.current_matched[self.highlighted]
                    chat_input.apply_file_suggestion(chosen_file, self.at_start_idx)
                self.display = False
                chat_input.focus()
            except Exception:
                pass
