import os

from core.domain.defaults.errors import ToolResult
from core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS
from core.tools.read.archive import _format_entry_size
from core.tools.read.cache import get_max_dir_entries


def _inspect_directory(path: str, start_line_int: int | None, end_line_int: int | None) -> ToolResult:
    try:
        raw_entries = sorted(os.listdir(path))
        total_count = len(raw_entries)
        max_dir_entries = get_max_dir_entries()

        normal_dirs, normal_files = [], []
        hidden_dirs, hidden_files = [], []

        for entry in raw_entries:
            full_p = os.path.join(path, entry)
            is_hidden = (
                entry in DEFAULT_IGNORE_DIRS
                or entry.startswith(".")
                or entry.endswith(".egg-info")
                or entry == "__pycache__"
            )
            if os.path.isdir(full_p):
                try:
                    count = len(os.listdir(full_p))
                    label = f"{entry}/ ({count} items)" if count != 1 else f"{entry}/ (1 item)"
                except Exception:
                    label = f"{entry}/"
                if is_hidden:
                    hidden_dirs.append(label)
                else:
                    normal_dirs.append(label)
            else:
                try:
                    sz = os.path.getsize(full_p)
                    label = f"{entry} ({_format_entry_size(sz)})"
                except Exception:
                    label = entry
                if is_hidden:
                    hidden_files.append(label)
                else:
                    normal_files.append(label)

        entries = normal_dirs + normal_files + hidden_dirs + hidden_files
        if total_count == 0:
            content_str = f"[dir {path} | total 0]"
        elif start_line_int is not None and start_line_int > total_count:
            return ToolResult.error(
                "range",
                detail=f"start_line ({start_line_int}) exceeds entry count ({total_count}) in '{path}'. Total entries: {total_count} (range: 1..{total_count}).",
                name="read",
            )
        elif start_line_int is not None or end_line_int is not None:
            s = max(1, start_line_int) if start_line_int else 1
            e = min(total_count, end_line_int) if end_line_int else min(total_count, s + max_dir_entries - 1)
            e = max(s, e)
            sliced = entries[s - 1 : e]
            body = "\n".join(sliced)
            content_str = f"[dir {path} | entries {s}..{e} of {total_count}]\n{body}"
        elif len(entries) > max_dir_entries:
            body = "\n".join(entries[:max_dir_entries])
            content_str = (
                f"[dir {path} | total {total_count} | truncated]\n"
                f"{body}\n"
                f"... [truncated | next read(path='{path}', start_line={max_dir_entries + 1})]"
            )
        else:
            body = "\n".join(entries)
            content_str = f"[dir {path} | total {total_count}]\n{body}"

        return ToolResult.done(
            content=content_str,
            display=f"[dir {path} | total {total_count}]",
        )
    except Exception as e:
        return ToolResult.error("listing", detail=str(e), name=path)
