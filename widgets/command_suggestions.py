import asyncio
import os
import time

from rich.markup import escape
from textual.widgets import OptionList

from widgets.app.command_provider import get_all_command_suggestions
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.constants import MESSAGE_INPUT
from widgets.utils.responsive import resolve_width
from widgets.utils.row_format import display_width, ellipsize


class CommandSuggestions(HeaderWrapOptionList):
    """Dropdown suggestions menu for slash commands (/help, /rewind) and file attachments (@file)"""

    can_focus = False
    ALLOW_SELECT = True

    # Required by CommandSuggestions to render slash commands. Delegates to the
    # app-layer provider (imported at module top).
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mode: str | None = None  # "command" or "file"
        self.current_matched: list[str] = []
        self.at_start_idx: int = -1
        self._cached_files: list[str] = []
        self._cached_cwd: str = ""
        self._cache_time: float = 0.0

    def _load_workspace_files(self) -> list[str]:
        """Sync disk walk of the workspace (run inside asyncio.to_thread)."""
        files_list = []
        cwd = os.getcwd()
        real_cwd = os.path.realpath(cwd)
        home = os.path.realpath(os.path.expanduser("~"))

        is_home_or_root = real_cwd == home or os.path.dirname(real_cwd) == real_cwd
        try:
            from core.infrastructure.config.settings import get_settings
            cfg_limit = get_settings().ui.autocomplete_max_files
        except Exception:
            cfg_limit = 1000
        max_files = min(300, cfg_limit) if is_home_or_root else cfg_limit

        from core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS

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
        return sorted(set(files_list))

    async def get_workspace_files(self) -> list[str]:
        """Gets relative file paths list in current project with 30s caching, async disk walk."""
        now = time.time()
        cwd = os.getcwd()
        if (
            self._cached_files
            and getattr(self, "_cached_cwd", None) == cwd
            and now - self._cache_time < 30.0
        ):
            return self._cached_files
        files_list = await asyncio.to_thread(self._load_workspace_files)
        self._cached_files = files_list
        self._cached_cwd = cwd
        self._cache_time = now
        return self._cached_files

    def _render_file_suggestions(self, files: list[str], query_lower: str) -> list[str]:
        """Build option rows from the (already cached) file list for the given query."""
        self.clear_options()
        # Viewport-aware layout: align the File/Dir tag at column 46 when the
        # terminal is wide enough, shrink the alignment column on narrow ones,
        # and ellipsize long paths so the kind tag always stays visible.
        row_budget = max(24, resolve_width(self) - 6)
        name_budget = row_budget - len(" Dir") - 1
        align_col = min(46, max(12, name_budget))
        matched_files = []
        seen: set[str] = set()
        for f in files:
            if f in seen:
                continue
            seen.add(f)
            if not query_lower or query_lower in f.lower():
                matched_files.append(f)
                kind = "Dir" if f.endswith("/") else "File"
                display_name = f if display_width(f) <= align_col else ellipsize(f, align_col)
                pad = max(0, align_col - display_width(display_name))
                padding_spaces = " " * pad
                formatted_line = f"{escape(display_name)}{padding_spaces} [dim]{kind}[/dim]"
                self.add_option(formatted_line)
                if len(matched_files) >= 50:
                    break
        self.current_matched = matched_files
        if matched_files:
            self._set_display(True)
            self.highlighted = 0
        else:
            self._set_display(False)
        return matched_files

    def _set_display(self, show: bool) -> None:
        self.display = show
        if show:
            try:
                if self.app:
                    from widgets.chat_input import ChatInput

                    ci = self.app.query_one(MESSAGE_INPUT, ChatInput)
                    ci.update_height()
            except Exception:
                pass

    async def update_query(self, full_text: str, current_line: str = "", cursor_col: int | None = None) -> list[str]:
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
                    all_cmds = await get_all_command_suggestions()
                    max_cmd_len = max((len(c) for c, _ in all_cmds), default=14)
                    padding = max(16, max_cmd_len + 2)
                    row_budget = max(30, resolve_width(self) - 6)
                    primary_matches = []
                    alias_matches = []
                    for cmd, desc in all_cmds:
                        if not cmd.lower().startswith(query_lower):
                            continue
                        is_alias = desc.startswith("Alias for ")
                        if query_lower == "/" and is_alias:
                            continue
                        if is_alias:
                            alias_matches.append((cmd, desc))
                        else:
                            primary_matches.append((cmd, desc))

                    combined = primary_matches + alias_matches
                    for cmd, desc in combined:
                        matched_cmds.append(cmd)
                        clean_desc = " ".join(desc.split())
                        # Description budget: from the tag column to the right
                        # edge; dynamically sizes to available row budget instead
                        # of an arbitrary 60-char ceiling.
                        desc_start = max(display_width(cmd), padding) + 1
                        clean_desc = ellipsize(clean_desc, max(10, row_budget - desc_start))
                        escaped_cmd = escape(cmd)
                        escaped_desc = escape(clean_desc)
                        pad = max(0, padding - display_width(cmd))
                        padding_spaces = " " * pad
                        formatted_line = f"{escaped_cmd}{padding_spaces} [dim]{escaped_desc}[/dim]"
                        self.add_option(formatted_line)

                    self.current_matched = matched_cmds
                    if matched_cmds:
                        self._set_display(True)
                        self.highlighted = 0
                    else:
                        self._set_display(False)
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
                    files = await self.get_workspace_files()
                    return self._render_file_suggestions(files, query_lower)

        if self.mode is not None or self.display or self.option_count:
            self.clear_options()
            self._set_display(False)
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

                chat_input = self.app.query_one(MESSAGE_INPUT, ChatInput)
                if self.mode == "command":
                    chosen_cmd = self.current_matched[self.highlighted]
                    chat_input.apply_suggestion(chosen_cmd, self.at_start_idx)
                elif self.mode == "file":
                    chosen_file = self.current_matched[self.highlighted]
                    chat_input.apply_file_suggestion(chosen_file, self.at_start_idx)
                self._set_display(False)
                chat_input.focus()
            except Exception:
                pass
