import difflib
import os
from typing import Any, Dict, Tuple

from core.domain.defaults.errors import ToolResult, format_tool_error
from core.infrastructure.runtime.git_utils import make_git_diff
from tools.base import (
    BaseTool,
    resolve_path,
    write_file_text,
)
from tools.cancel import run_cancellable

LEFT_SINGLE_CURLY_QUOTE = "‘"
RIGHT_SINGLE_CURLY_QUOTE = "’"
LEFT_DOUBLE_CURLY_QUOTE = "“"
RIGHT_DOUBLE_CURLY_QUOTE = "”"


def normalize_quotes(s: str) -> str:
    return (
        s.replace(LEFT_SINGLE_CURLY_QUOTE, "'")
        .replace(RIGHT_SINGLE_CURLY_QUOTE, "'")
        .replace(LEFT_DOUBLE_CURLY_QUOTE, '"')
        .replace(RIGHT_DOUBLE_CURLY_QUOTE, '"')
    )


def _preserve_quote_style(old_str: str, actual_old_str: str, new_str: str) -> str:
    if old_str == actual_old_str:
        return new_str

    has_double = LEFT_DOUBLE_CURLY_QUOTE in actual_old_str or RIGHT_DOUBLE_CURLY_QUOTE in actual_old_str
    has_single = LEFT_SINGLE_CURLY_QUOTE in actual_old_str or RIGHT_SINGLE_CURLY_QUOTE in actual_old_str

    if not has_double and not has_single:
        return normalize_quotes(new_str)

    res = new_str
    if has_double:
        res = res.replace('"', RIGHT_DOUBLE_CURLY_QUOTE)
    if has_single:
        res = res.replace("'", RIGHT_SINGLE_CURLY_QUOTE)
    return res


def find_actual_target_and_replacement(text: str, target: str, replacement: str) -> Tuple[str, str]:
    actual_target = target
    actual_replacement = replacement

    if target not in text:
        norm_text = normalize_quotes(text)
        norm_target = normalize_quotes(target)
        idx = norm_text.find(norm_target)
        if idx != -1:
            actual_target = text[idx : idx + len(target)]
            actual_replacement = _preserve_quote_style(target, actual_target, replacement)
        else:
            # CRLF <-> LF mismatch: retry with the line endings swapped so a
            # CRLF file can still be edited with an LF old_str and vice versa.
            swapped = target.replace("\n", "\r\n") if "\r\n" not in target else target.replace("\r\n", "\n")
            if swapped != target and swapped in text:
                actual_target = swapped
                actual_replacement = (
                    replacement.replace("\n", "\r\n") if "\r\n" in swapped else replacement.replace("\r\n", "\n")
                )

    if actual_replacement == "" and not actual_target.endswith(("\n", "\r")):
        if actual_target + "\r\n" in text:
            actual_target += "\r\n"
        elif actual_target + "\n" in text:
            actual_target += "\n"

    return actual_target, actual_replacement


def _generate_fuzzy_match_hint(current_text: str, target: str, path: str) -> str:
    target_lines = [line_item.strip() for line_item in target.splitlines() if line_item.strip()]
    if not target_lines:
        return ""

    first_line_target = target_lines[0]
    file_lines = current_text.splitlines()

    close_lines = difflib.get_close_matches(
        first_line_target, [line_item.strip() for line_item in file_lines], n=2, cutoff=0.4
    )
    if close_lines:
        target_close = close_lines[0]
        match_line_num = None
        for idx, line in enumerate(file_lines, start=1):
            if target_close == line.strip() or target_close in line.strip():
                match_line_num = idx
                break

        if match_line_num is not None:
            start_snip = max(1, match_line_num - 2)
            end_snip = min(len(file_lines), match_line_num + len(target_lines) + 2)
            snippet_lines = file_lines[start_snip - 1 : end_snip]
            snippet_str = "\n".join(
                f"{i:4d} | {line_item}" for i, line_item in enumerate(snippet_lines, start=start_snip)
            )
            return (
                f"\n\n[Hint: Nearest matching code in '{path}' around line {match_line_num}]:\n"
                f"{snippet_str}\n"
                f"[Re-try with old_str matching this snippet and include 2-4 lines of surrounding context]"
            )
    return ""


def apply_edit(content: str, old_str: str, new_str: str, replace_all: bool = False, path: str = "file") -> Tuple[str, str]:
    if old_str is None:
        raise ValueError(format_tool_error("params", "missing 'old_str'"))
    if old_str == "":
        raise ValueError(format_tool_error("params", "old_str cannot be empty"))
    if new_str is None:
        raise ValueError(format_tool_error("params", "missing 'new_str'"))
    if old_str == new_str:
        raise ValueError(format_tool_error("params", "new_str must be different from old_str"))

    actual_target, actual_replacement = find_actual_target_and_replacement(content, old_str, new_str)
    count = content.count(actual_target)

    if count == 0:
        hint = _generate_fuzzy_match_hint(content, old_str, path)
        raise ValueError(format_tool_error("match", f"exact block not found in '{path}'.{hint}"))

    if count > 1 and not replace_all:
        raise ValueError(
            format_tool_error(
                "match",
                f"target matches {count} occurrences in '{path}'. "
                f"Include 2-4 lines of surrounding context to make old_str unique, or set replace_all=true.",
            )
        )

    if replace_all:
        new_content = content.replace(actual_target, actual_replacement)
    else:
        new_content = content.replace(actual_target, actual_replacement, 1)

    diff_output = make_git_diff(content, new_content, fromfile=f"a/{path}", tofile=f"b/{path}")
    return new_content, diff_output


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Replace text in a file. 'old_str' must be unique in the file (include 2-4 lines of surrounding "
        "context if needed). Set 'replace_all=true' to replace all occurrences."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "edit",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "old_str": {
                        "type": "string",
                        "description": "Exact text to replace. Must be unique in the file (include 2-4 lines of surrounding context if needed).",
                    },
                    "new_str": {"type": "string", "description": "New replacement text"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences of old_str across the file (default: false).",
                    },
                },
                "required": ["path", "old_str", "new_str"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)

        path_arg = args.get("path") or args.get("file_path") or args.get("filePath")
        if not path_arg or not str(path_arg).strip():
            return ToolResult.error("params", name="path", detail="missing or empty")

        old_str = args.get("old_str")
        if old_str is None:
            old_str = args.get("old_string", args.get("oldString"))

        new_str = args.get("new_str")
        if new_str is None:
            new_str = args.get("new_string", args.get("newString", ""))

        replace_all = bool(args.get("replace_all", args.get("allow_multiple", False)))

        path = resolve_path(str(path_arg), cwd=ctx.cwd)

        def _do_edit() -> ToolResult:
            if not path or not os.path.exists(path):
                return ToolResult.error("file", name=path, detail="not found")
            if os.path.isdir(path):
                return ToolResult.error("file", name=path, detail="is a directory")

            # Read with newline="" to keep \r\n line endings intact: the default
            # universal-newline mode would collapse CRLF -> LF and silently rewrite
            # the whole file in LF on write-back (regression: CRLF file edits).
            with open(path, "r", encoding="utf-8", newline="") as f:
                content = f.read()

            new_content, diff = apply_edit(content, old_str, new_str, replace_all, path)
            write_file_text(path, new_content)
            return ToolResult.done(diff)

        try:
            return await run_cancellable(_do_edit)
        except (UnicodeDecodeError, UnicodeEncodeError) as ue:
            return ToolResult.error("file", detail=str(ue), name=path)
        except ValueError as ve:
            msg = str(ve)
            if msg.startswith("ERR:"):
                from core.domain.defaults.errors import ToolResultStatus
                return ToolResult(content=msg, status=ToolResultStatus.ERROR)
            return ToolResult.error("params", detail=msg)
        except Exception as e:
            return ToolResult.error("file", detail=str(e), name=path)
