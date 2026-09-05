import os

from core.domain.defaults.errors import ToolResult

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)


def is_archive_file(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def _format_entry_size(size_bytes: int) -> str:
    """Format bytes into a human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _inspect_archive(
    path: str,
    max_entries: int,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ToolResult:
    import tarfile
    import zipfile

    lower = path.lower()
    dirs: set[str] = set()
    files: list[str] = []

    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if not name or "__MACOSX" in name or os.path.basename(name).startswith("._"):
                        continue
                    if info.is_dir() or name.endswith("/"):
                        dirs.add(name.rstrip("/") + "/")
                    else:
                        files.append(f"{name} ({_format_entry_size(info.file_size)})")
        else:
            with tarfile.open(path, "r:*") as tf:
                for member in tf.getmembers():
                    name = member.name
                    if not name or "__MACOSX" in name or os.path.basename(name).startswith("._"):
                        continue
                    if member.isdir() or name.endswith("/"):
                        dirs.add(name.rstrip("/") + "/")
                    else:
                        files.append(f"{name} ({_format_entry_size(member.size)})")

        entries = sorted(dirs) + sorted(files)
        total_count = len(entries)
        if total_count == 0:
            content_str = f"[archive {path} | total 0]"
        elif start_line is not None and start_line > total_count:
            return ToolResult.error(
                "range",
                detail=f"start_line ({start_line}) exceeds entry count ({total_count}) in '{path}'. Total entries: {total_count} (range: 1..{total_count}).",
                name="read",
            )
        elif start_line is not None or end_line is not None:
            s = max(1, start_line) if start_line else 1
            e = min(total_count, end_line) if end_line else min(total_count, s + max_entries - 1)
            e = max(s, e)
            sliced = entries[s - 1 : e]
            body = "\n".join(sliced)
            content_str = f"[archive {path} | entries {s}..{e} of {total_count}]\n{body}"
        elif total_count > max_entries:
            body = "\n".join(entries[:max_entries])
            content_str = (
                f"[archive {path} | total {total_count} | truncated]\n"
                f"{body}\n"
                f"... [truncated | next read(path='{path}', start_line={max_entries + 1})]"
            )
        else:
            body = "\n".join(entries)
            content_str = f"[archive {path} | total {total_count}]\n{body}"

        return ToolResult.done(
            content=content_str,
            display="",
        )
    except Exception as e:
        return ToolResult.error("archive", detail=str(e), name=path)
