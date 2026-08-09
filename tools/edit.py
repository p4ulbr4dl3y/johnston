import asyncio
import difflib
import os
from typing import Any, Dict, List, Tuple

from core.linters_manager import get_linters_manager
from tools.base import BaseTool, make_unified_diff, resolve_path, try_int, write_file_text

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


def find_actual_target_and_replacement(
    text: str, target: str, replacement: str
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

    close_lines = difflib.get_close_matches(first_line_target, [line_item.strip() for line_item in file_lines], n=2, cutoff=0.4)
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
            snippet_lines = file_lines[start_snip - 1:end_snip]
            snippet_str = "\n".join(f"{i:4d} | {line_item}" for i, line_item in enumerate(snippet_lines, start=start_snip))
            return (
                f"\n\n[Hint: Nearest matching code in '{path}' around line {match_line_num}]:\n"
                f"{snippet_str}\n"
                f"[Re-try with target_content matching this snippet and pass start_line={start_snip}, end_line={end_snip}]"
            )
    return ""


def apply_chunk_replacements(
    content: str,
    raw_chunks: List[Dict[str, Any]],
    path: str
) -> Tuple[str, str]:
    if not raw_chunks:
        raise ValueError("ERR: no replacement chunks provided")

    parsed_chunks = []
    for idx, c in enumerate(raw_chunks, start=1):
        target = c.get("old_str")
        if target is None:
            target = c.get("target_content")
        if target is None:
            target = c.get("old_string")
        if target is None:
            raise ValueError(f"ERR: chunk {idx} missing 'old_str' or 'target_content'")

        if target == "":
            raise ValueError(f"ERR: chunk {idx} old_str (target_content) cannot be empty")

        replacement = c.get("new_str")
        if replacement is None:
            replacement = c.get("replacement_content")
        if replacement is None:
            replacement = c.get("new_string")
        if replacement is None:
            raise ValueError(f"ERR: chunk {idx} missing 'new_str' or 'replacement_content'")

        s_line_int = try_int(c.get("start_line"))
        e_line_int = try_int(c.get("end_line"))
        allow_mult = bool(c.get("allow_multiple", False))

        parsed_chunks.append({
            "idx": idx,
            "target": target,
            "replacement": replacement,
            "start_line": s_line_int,
            "end_line": e_line_int,
            "allow_multiple": allow_mult
        })

    # Sort chunks descending by start_line to prevent line-offset drift during multi-chunk replacement
    parsed_chunks.sort(key=lambda item: (item["start_line"] or 0), reverse=True)

    # Check for overlapping explicit line ranges among chunks
    ranged_chunks = [c for c in parsed_chunks if c["start_line"] is not None and c["end_line"] is not None]
    for i in range(len(ranged_chunks)):
        for j in range(i + 1, len(ranged_chunks)):
            c1, c2 = ranged_chunks[i], ranged_chunks[j]
            s1, e1 = c1["start_line"], c1["end_line"]
            s2, e2 = c2["start_line"], c2["end_line"]
            if max(s1, s2) <= min(e1, e2):
                raise ValueError(
                    f"ERR: replacement chunks {c1['idx']} (lines {s1}-{e1}) and "
                    f"{c2['idx']} (lines {s2}-{e2}) overlap in '{path}'"
                )

    lines = content.splitlines(keepends=True)
    for c in parsed_chunks:
        target = c["target"]
        replacement = c["replacement"]
        s_line = c["start_line"]
        e_line = c["end_line"]
        allow_mult = c["allow_multiple"]

        current_text = "".join(lines)

        if s_line is not None or e_line is not None:
            in_bounds = True
            if s_line is not None and s_line > len(lines):
                in_bounds = False

            if in_bounds:
                start_idx = (s_line - 1) if (s_line and s_line > 0) else 0
                end_idx = e_line if (e_line and e_line <= len(lines)) else len(lines)

                target_line_count = len(target.splitlines()) if target.splitlines() else 1
                effective_end_idx = max(end_idx, start_idx + target_line_count)

                sub_lines = lines[start_idx:effective_end_idx]
                sub_text = "".join(sub_lines)

                actual_target, actual_replacement = find_actual_target_and_replacement(sub_text, target, replacement)
                count = sub_text.count(actual_target)
            else:
                count = 0
                actual_target = target
                actual_replacement = replacement

            if count == 0:
                actual_target_full, actual_replacement_full = find_actual_target_and_replacement(current_text, target, replacement)
                full_count = current_text.count(actual_target_full)

                if full_count == 1:
                    new_text = current_text.replace(actual_target_full, actual_replacement_full, 1)
                    lines = new_text.splitlines(keepends=True)
                    continue

                if not in_bounds:
                    raise ValueError(
                        f"ERR: start_line ({s_line}) exceeds file line count ({len(lines)}) in '{path}'. "
                        f"[Hint: File has {len(lines)} total lines. Re-try edit with start_line between 1 and {len(lines)}]"
                    )

                target_first_line = actual_target_full.splitlines()[0] if actual_target_full.splitlines() else actual_target_full
                found_line = None
                for l_no, line_str in enumerate(lines, start=1):
                    if target_first_line in line_str:
                        found_line = l_no
                        break
                hint = _generate_fuzzy_match_hint(current_text, target, path)
                if full_count > 1 and not allow_mult:
                    loc_msg = f" Target content matches {full_count} occurrences in full file (around line {found_line})." if found_line else ""
                    raise ValueError(
                        f"ERR: target not found in specified range ({s_line}-{e_line}) and matches multiple occurrences ({full_count}) in '{path}'.{loc_msg}{hint}"
                    )
                else:
                    loc_msg = f" Target content was found elsewhere around line {found_line}." if found_line else ""
                    raise ValueError(
                        f"ERR: target not found in '{path}' ({s_line}-{e_line}).{loc_msg}{hint}"
                    )

            if count > 1 and not allow_mult:
                raise ValueError(
                    f"ERR: target matches {count} occurrences in lines {s_line}-{e_line} of '{path}'. "
                    f"Narrow start_line/end_line range or include more lines to make target unique."
                )

            new_sub_text = sub_text.replace(actual_target, actual_replacement, 1 if not allow_mult else -1)
            sub_replacement_lines = new_sub_text.splitlines(keepends=True)
            if sub_text.endswith(("\n", "\r")) and sub_replacement_lines and not sub_replacement_lines[-1].endswith(("\n", "\r")):
                eol = "\r\n" if sub_text.endswith("\r\n") else "\n"
                sub_replacement_lines[-1] += eol
            lines[start_idx:effective_end_idx] = sub_replacement_lines

        else:
            current_text = "".join(lines)
            actual_target, actual_replacement = find_actual_target_and_replacement(current_text, target, replacement)

            count = current_text.count(actual_target)
            if count == 0:
                hint = _generate_fuzzy_match_hint(current_text, target, path)
                raise ValueError(
                    f"ERR: exact block not found in '{path}'.{hint}"
                )
            if count > 1 and not allow_mult:
                raise ValueError(
                    f"ERR: target matches {count} occurrences in '{path}'. "
                    f"Specify start_line and end_line or include more surrounding lines to make target unique."
                )

            new_text = current_text.replace(actual_target, actual_replacement, 1 if not allow_mult else -1)
            lines = new_text.splitlines(keepends=True)

    new_content = "".join(lines)
    diff_output = make_unified_diff(content, new_content, fromfile=path + " (old)", tofile=path + " (new)")
    return new_content, diff_output


async def _execute_edit_helper(path_arg: str, raw_chunks: List[Dict[str, Any]], cwd: str = None) -> str:
    path = resolve_path(path_arg, cwd=cwd)
    if not path or not os.path.exists(path):
        return f"ERR: file '{path}' not found"
    if os.path.isdir(path):
        return f"ERR: '{path}' is a directory"

    def _do_edit():
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        new_content, diff = apply_chunk_replacements(content, raw_chunks, path)
        write_file_text(path, new_content)
        return diff

    try:
        diff_output = await asyncio.to_thread(_do_edit)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"ERR: file '{path}': {e}"

    linter_output = await get_linters_manager().run_for(path)
    return diff_output + linter_output


class EditTool(BaseTool):
    name = "edit"
    description = "Replace a single contiguous code block in a file."
    schema = {
        "type": "function",
        "function": {
            "name": "edit",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_str": {"type": "string", "description": "Code block to replace"},
                    "new_str": {"type": "string", "description": "New code block"},
                    "start": {"type": "integer", "description": "Start line (1-indexed)"},
                    "end": {"type": "integer", "description": "End line (inclusive)"},
                    "multiple": {"type": "boolean", "description": "Allow multiple matches"}
                },
                "required": ["path", "old_str", "new_str"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        path = args.get("path") or args.get("target_file", "")
        chunks = args.get("edits") or args.get("replacement_chunks") or args.get("ReplacementChunks")
        if chunks and isinstance(chunks, list):
            return await _execute_edit_helper(path, chunks, cwd=ctx.cwd)

        target_val = args.get("old_str", args.get("target_content", args.get("old_string", "")))
        repl_val = args.get("new_str", args.get("replacement_content", args.get("new_string", "")))
        chunk = {
            "target_content": target_val,
            "replacement_content": repl_val,
            "start_line": args.get("start", args.get("start_line")),
            "end_line": args.get("end", args.get("end_line")),
            "allow_multiple": args.get("multiple", args.get("allow_multiple", False)),
        }
        return await _execute_edit_helper(path, [chunk], cwd=ctx.cwd)


class MultiEditTool(BaseTool):
    name = "multi_edit"
    description = "Replace multiple non-contiguous code blocks in one file."
    schema = {
        "type": "function",
        "function": {
            "name": "multi_edit",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "edits": {
                        "type": "array",
                        "description": "List of edit chunks",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_str": {"type": "string", "description": "Exact text to replace"},
                                "new_str": {"type": "string", "description": "New code block"},
                                "start": {"type": "integer", "description": "Start line (1-indexed)"},
                                "end": {"type": "integer", "description": "End line (inclusive)"},
                                "multiple": {"type": "boolean", "description": "Allow multiple matches"}
                            }
                        }
                    }
                },
                "required": ["path", "edits"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        path = args.get("path") or args.get("target_file", "")
        raw_chunks = args.get("edits") or args.get("replacement_chunks") or args.get("chunks") or []
        return await _execute_edit_helper(path, raw_chunks, cwd=ctx.cwd)

