import difflib
import re
from typing import Any, Dict, Tuple

from core.domain.defaults.errors import ToolResult
from tools.base import (
    BaseTool,
    write_file_text,
)
from tools.cancel import run_cancellable
from tools.utils import (
    format_file_diff,
    resolve_writable_path,
    validate_file_for_edit,
)

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


def _normalize_indentation(s: str, is_markdown: bool = False) -> Tuple[str, list[int]]:
    normalized_chars: list[str] = []
    mapping: list[int] = []
    i = 0
    n = len(s)
    while i < n:
        char = s[i]
        if char in ("\n", "\r"):
            normalized_chars.append(char)
            mapping.append(i)
            i += 1
        elif char in (" ", "\t"):
            start_ws = i
            while i < n and s[i] in (" ", "\t"):
                i += 1
            is_leading = start_ws == 0 or s[start_ws - 1] in ("\n", "\r")
            is_trailing = i == n or s[i] in ("\n", "\r")
            if is_leading:
                pass
            elif is_trailing and not is_markdown:
                pass
            else:
                for k in range(start_ws, i):
                    normalized_chars.append(s[k])
                    mapping.append(k)
        else:
            normalized_chars.append(char)
            mapping.append(i)
            i += 1
    return "".join(normalized_chars), mapping


def find_whitespace_agnostic_match(file_content: str, search_string: str, is_markdown: bool = False) -> str | None:
    search_norm, search_mapping = _normalize_indentation(search_string, is_markdown)
    if not search_norm.strip():
        return None

    file_norm, file_mapping = _normalize_indentation(file_content, is_markdown)
    match_index = file_norm.find(search_norm)
    if match_index == -1:
        return None

    if file_norm.find(search_norm, match_index + 1) != -1:
        return None

    if match_index >= len(file_mapping) or (match_index + len(search_norm) - 1) >= len(file_mapping):
        return None

    original_start = file_mapping[match_index]
    original_end = file_mapping[match_index + len(search_norm) - 1]

    start = original_start
    end = original_end

    if search_string and search_string[0] in (" ", "\t"):
        while start > 0 and file_content[start - 1] in (" ", "\t"):
            start -= 1
    elif search_string and search_string[0].isspace():
        while start > 0 and file_content[start - 1].isspace():
            start -= 1

    if search_string.endswith(("\n", "\r\n", "\r")):
        while end > start and file_content[end] in (" ", "\t"):
            end -= 1
    elif search_string and search_string[-1] in (" ", "\t"):
        while end + 1 < len(file_content) and file_content[end + 1] in (" ", "\t"):
            end += 1
    elif search_string and search_string[-1].isspace():
        while end + 1 < len(file_content) and file_content[end + 1].isspace():
            end += 1

    return file_content[start : end + 1]


def adjust_new_string_indentation(old_string: str, file_match: str, new_string: str) -> str | None:
    if old_string == file_match:
        return new_string

    old_norm, old_mapping = _normalize_indentation(old_string, False)
    actual_norm, actual_mapping = _normalize_indentation(file_match, False)

    match_index = actual_norm.find(old_norm)
    if match_index == -1:
        return new_string

    indent_map: dict[str, str] = {}
    old_lines = old_string.split("\n")
    old_char_index = 0

    for line in old_lines:
        leading_ws_match = re.match(r"^[ \t]*", line)
        old_indent = leading_ws_match.group(0) if leading_ws_match else ""

        non_ws_match = re.search(r"\S", line)
        if non_ws_match:
            non_ws_index_in_line = non_ws_match.start()
            non_ws_index_in_old = old_char_index + non_ws_index_in_line

            norm_index = -1
            for k, mapped_pos in enumerate(old_mapping):
                if mapped_pos == non_ws_index_in_old:
                    norm_index = k
                    break

            if norm_index != -1:
                actual_norm_index = match_index + norm_index
                if actual_norm_index < len(actual_mapping):
                    actual_char_index = actual_mapping[actual_norm_index]

                    start_of_line = actual_char_index
                    while start_of_line > 0 and file_match[start_of_line - 1] != "\n":
                        start_of_line -= 1

                    actual_indent = ""
                    for k in range(start_of_line, actual_char_index):
                        if file_match[k] in (" ", "\t"):
                            actual_indent += file_match[k]
                        else:
                            break

                    if old_indent in indent_map and indent_map[old_indent] != actual_indent:
                        return None

                    indent_map[old_indent] = actual_indent

        old_char_index += len(line) + 1

    if not indent_map:
        return new_string

    new_lines = new_string.split("\n")
    adjusted_lines: list[str] = []

    for line in new_lines:
        if not line.strip():
            adjusted_lines.append(line)
            continue

        leading_ws_match = re.match(r"^[ \t]*", line)
        new_indent = leading_ws_match.group(0) if leading_ws_match else ""

        if new_indent in indent_map:
            adjusted_lines.append(indent_map[new_indent] + line[len(new_indent) :])
            continue

        longest_prefix = ""
        mapped_prefix = ""
        for old_ind, actual_ind in indent_map.items():
            if new_indent.startswith(old_ind) and len(old_ind) > len(longest_prefix):
                longest_prefix = old_ind
                mapped_prefix = actual_ind

        if longest_prefix:
            remaining_indent = new_indent[len(longest_prefix) :]
            adjusted_lines.append(mapped_prefix + remaining_indent + line[len(new_indent) :])
        else:
            adjusted_lines.append(line)

    return "\n".join(adjusted_lines)


def find_actual_target_and_replacement(
    text: str, target: str, replacement: str, path: str = ""
) -> Tuple[str, str]:
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
            else:
                is_md = path.lower().endswith((".md", ".mdx"))
                fuzzy_match = find_whitespace_agnostic_match(text, target, is_md)
                if fuzzy_match:
                    adj_rep = adjust_new_string_indentation(target, fuzzy_match, replacement)
                    if adj_rep is not None:
                        actual_target = fuzzy_match
                        actual_replacement = adj_rep

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
                f"{i}|{line_item}" for i, line_item in enumerate(snippet_lines, start=start_snip)
            )
            return (
                f"\nClosest match in '{path}' at line {match_line_num}:\n"
                f"{snippet_str}"
            )
    return ""


def apply_edit(
    content: str, old_str: str, new_str: str, replace_all: bool = False, path: str = "file"
) -> Tuple[str, str] | ToolResult:
    if old_str is None:
        return ToolResult.error("params", detail="missing 'old_str'")
    if old_str == "":
        return ToolResult.error("params", detail="old_str cannot be empty")
    if new_str is None:
        return ToolResult.error("params", detail="missing 'new_str'")
    if old_str == new_str:
        return ToolResult.error("params", detail="new_str must be different from old_str")

    actual_target, actual_replacement = find_actual_target_and_replacement(content, old_str, new_str, path=path)
    count = content.count(actual_target)

    if count == 0:
        hint = _generate_fuzzy_match_hint(content, old_str, path)
        return ToolResult.error("match_not_found", detail=f"exact block not found in '{path}'.{hint}")

    if count > 1 and not replace_all:
        return ToolResult.error(
            "match_ambiguous",
            detail=(
                f"target matches {count} occurrences in '{path}'. "
                f"Include 2-4 lines of surrounding context to make old_str unique, or set replace_all=true."
            ),
        )

    if replace_all:
        new_content = content.replace(actual_target, actual_replacement)
    else:
        new_content = content.replace(actual_target, actual_replacement, 1)

    diff_output = format_file_diff(content, new_content, path)
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
            "description": (
                "Replace text in an EXISTING file via exact-match. For NEW files, use `create`. "
                "Always `read` the file first to see current content.\n\n"
                "`old_str` rules:\n"
                "- Must be unique in the file. Include 2-4 lines of surrounding context if needed.\n"
                "- Whitespace-agnostic at line starts (tabs/spaces normalized). CRLF/LF handled.\n"
                "- Quote-style preserved: curly quotes stay curly if file uses them.\n"
                "- If not found, error includes a fuzzy-match hint with the closest line.\n\n"
                "`new_str` rules:\n"
                "- Empty string OR absent key = DELETE the matched block.\n"
                "- `replace_all=true` replaces all occurrences (else error on multi-match).\n\n"
                "Atomic write via temp file + rename. Limits: file ≤10MB, regular file, UTF-8.\n\n"
                "Error kinds: `match_not_found` (with fuzzy hint), `match_ambiguous` (multi-match), "
                "`params` (missing/empty/equal old/new), `not_found` (file missing), `is_directory`, "
                "`encoding`, `size_exceeded`, `permission` (sandbox), `execute` (write failure)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path. Must exist and be a regular file. Use relative path.",
                    },
                    "old_str": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Exact text to replace. Must be unique. Whitespace-agnostic at line starts.",
                    },
                    "new_str": {
                        "type": "string",
                        "description": "Replacement text. Empty or absent = delete old_str.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "default": False,
                        "description": "Replace all occurrences (else error if more than 1 match).",
                    },
                },
                "required": ["path", "old_str"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)

        path_arg = args.get("path")
        path, err = resolve_writable_path(ctx, path_arg)
        if err is not None:
            return err

        old_str = args.get("old_str")

        new_str = args.get("new_str")
        if new_str is None:
            # Absent key means deletion (pinned by test_edit_missing_new_str_is_delete):
            # keeps single-turn deletes for providers that drop empty-string args.
            new_str = ""

        replace_all = bool(args.get("replace_all", False))

        def _do_edit() -> ToolResult:
            val_err = validate_file_for_edit(path)
            if val_err is not None:
                return val_err

            # Read with newline="" to keep \r\n line endings intact: the default
            # universal-newline mode would collapse CRLF -> LF and silently rewrite
            # the whole file in LF on write-back (regression: CRLF file edits).
            with open(path, "r", encoding="utf-8", newline="") as f:
                content = f.read()

            res = apply_edit(content, old_str, new_str, replace_all, path)
            if isinstance(res, ToolResult):
                return res

            new_content, diff = res
            write_file_text(path, new_content)
            return ToolResult.done(content=diff, display=diff)

        try:
            return await run_cancellable(_do_edit)
        except (UnicodeDecodeError, UnicodeEncodeError) as ue:
            return ToolResult.error("encoding", detail=str(ue), name=path)
        except ValueError as ve:
            # Unexpected ValueError: wrap as params.
            return ToolResult.error("params", detail=str(ve))
        except Exception as e:
            return ToolResult.error("execute", detail=f"write failed: {e}", name=path)

