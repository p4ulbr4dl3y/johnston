import asyncio
import difflib
import os
from typing import Any, Dict, List, Tuple

from tools.base import BaseTool, atomic_write_text, resolve_path
from tools.linter import run_linter


def _generate_fuzzy_match_hint(current_text: str, target: str, path: str) -> str:
    target_lines = [line_item.strip() for line_item in target.splitlines() if line_item.strip()]
    if not target_lines:
        return ""

    first_line_target = target_lines[0]
    file_lines = current_text.splitlines()

    close_lines = difflib.get_close_matches(first_line_target, [line_item.strip() for line_item in file_lines], n=2, cutoff=0.4)
    if close_lines:
        match_line_num = 1
        for idx, line in enumerate(file_lines, start=1):
            if close_lines[0] in line:
                match_line_num = idx
                break

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
        raise ValueError("Error: No replacement chunks provided.")

    parsed_chunks = []
    for idx, c in enumerate(raw_chunks, start=1):
        target = c.get("target_content")
        if target is None:
            target = c.get("old_string")
        if target is None:
            raise ValueError(f"Error: Chunk {idx} missing 'target_content' or 'old_string'.")

        if target == "":
            raise ValueError(f"Error: Chunk {idx} target_content (old_string) cannot be empty.")

        replacement = c.get("replacement_content")
        if replacement is None:
            replacement = c.get("new_string")
        if replacement is None:
            raise ValueError(f"Error: Chunk {idx} missing 'replacement_content' or 'new_string'.")

        s_line = c.get("start_line")
        e_line = c.get("end_line")
        allow_mult = bool(c.get("allow_multiple", False))

        try:
            s_line_int = int(s_line) if s_line is not None else None
        except (ValueError, TypeError):
            s_line_int = None

        try:
            e_line_int = int(e_line) if e_line is not None else None
        except (ValueError, TypeError):
            e_line_int = None

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

    lines = content.splitlines(keepends=True)
    for c in parsed_chunks:
        target = c["target"]
        replacement = c["replacement"]
        s_line = c["start_line"]
        e_line = c["end_line"]
        allow_mult = c["allow_multiple"]

        current_text = "".join(lines)

        if s_line is not None or e_line is not None:
            if s_line is not None and s_line > len(lines):
                raise ValueError(
                    f"Error: start_line ({s_line}) exceeds file line count ({len(lines)}) in '{path}'. "
                    f"[Hint: File has {len(lines)} total lines. Re-try edit with start_line between 1 and {len(lines)}]"
                )
            start_idx = (s_line - 1) if (s_line and s_line > 0) else 0
            end_idx = e_line if (e_line and e_line <= len(lines)) else len(lines)

            sub_lines = lines[start_idx:end_idx]
            sub_text = "".join(sub_lines)

            count = sub_text.count(target)
            if count == 0:
                target_first_line = target.splitlines()[0] if target.splitlines() else target
                found_line = 1
                for l_no, line_str in enumerate(lines, start=1):
                    if target_first_line in line_str:
                        found_line = l_no
                        break
                hint = _generate_fuzzy_match_hint(current_text, target, path)
                raise ValueError(
                    f"Error: target_content not found between lines {s_line} and {e_line} in '{path}'. "
                    f"Target content was found elsewhere around line {found_line}.{hint}"
                )

            if count > 1 and not allow_mult:
                raise ValueError(
                    f"Error: target_content matches {count} occurrences in lines {s_line}-{e_line} of '{path}'. "
                    f"Narrow start_line/end_line range or include more lines to make target unique."
                )

            new_sub_text = sub_text.replace(target, replacement, 1 if not allow_mult else -1)
            lines[start_idx:end_idx] = new_sub_text.splitlines(keepends=True)

        else:
            count = current_text.count(target)
            if count == 0:
                hint = _generate_fuzzy_match_hint(current_text, target, path)
                raise ValueError(
                    f"Error: exact block of text not found in '{path}'.{hint}"
                )
            if count > 1 and not allow_mult:
                raise ValueError(
                    f"Error: target_content matches {count} occurrences in '{path}'. "
                    f"Specify start_line and end_line or include more surrounding lines to make target unique."
                )

            new_text = current_text.replace(target, replacement, 1 if not allow_mult else -1)
            lines = new_text.splitlines(keepends=True)

    new_content = "".join(lines)
    diff_lines = list(difflib.unified_diff(
        content.splitlines(),
        new_content.splitlines(),
        fromfile=path + " (old)",
        tofile=path + " (new)",
        lineterm=""
    ))
    diff_output = "\n".join(diff_lines)
    return new_content, diff_output


async def _execute_edit_helper(path_arg: str, raw_chunks: List[Dict[str, Any]]) -> str:
    path = resolve_path(path_arg)
    if not path or not os.path.exists(path):
        return f"Error: file '{path}' not found."
    if os.path.isdir(path):
        return f"Error: '{path}' is a directory, not a file."

    def _do_edit():
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        new_content, diff = apply_chunk_replacements(content, raw_chunks, path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        atomic_write_text(path, new_content)
        return diff

    try:
        diff_output = await asyncio.to_thread(_do_edit)
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Error modifying file '{path}': {e}"

    linter_output = await run_linter(path)
    return diff_output + linter_output


class ReplaceFileContentTool(BaseTool):
    name = "replace_file_content"
    description = "Replace a single contiguous code block in a file."
    schema = {
        "type": "function",
        "function": {
            "name": "replace_file_content",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_file": {"type": "string", "description": "File path"},
                    "target_content": {"type": "string", "description": "Code block to replace"},
                    "replacement_content": {"type": "string", "description": "New code block"},
                    "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line (inclusive)"},
                    "allow_multiple": {"type": "boolean", "description": "Allow multiple matches"}
                },
                "required": ["target_file", "target_content", "replacement_content"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = args.get("target_file") or args.get("path", "")
        target_val = args.get("target_content") if "target_content" in args else args.get("old_string", "")
        repl_val = args.get("replacement_content") if "replacement_content" in args else args.get("new_string", "")
        chunk = {
            "target_content": target_val,
            "replacement_content": repl_val,
            "start_line": args.get("start_line"),
            "end_line": args.get("end_line"),
            "allow_multiple": args.get("allow_multiple", False),
        }
        return await _execute_edit_helper(path, [chunk])


class MultiReplaceFileContentTool(BaseTool):
    name = "multi_replace_file_content"
    description = "Replace multiple non-contiguous code blocks in a single file."
    schema = {
        "type": "function",
        "function": {
            "name": "multi_replace_file_content",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_file": {"type": "string", "description": "File path"},
                    "replacement_chunks": {
                        "type": "array",
                        "description": "List of edit chunks",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_content": {"type": "string"},
                                "replacement_content": {"type": "string"},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                                "allow_multiple": {"type": "boolean"}
                            }
                        }
                    }
                },
                "required": ["target_file", "replacement_chunks"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = args.get("target_file") or args.get("path", "")
        raw_chunks = args.get("replacement_chunks") or args.get("chunks") or []
        return await _execute_edit_helper(path, raw_chunks)

