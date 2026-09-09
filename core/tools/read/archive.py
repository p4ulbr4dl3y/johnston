import os

from core.domain.defaults.errors import ToolResult

ZIP_EXTENSIONS = (
    ".zip",
    ".whl",
    ".jar",
    ".war",
    ".ear",
    ".apk",
)

TAR_EXTENSIONS = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)

ARCHIVE_EXTENSIONS = ZIP_EXTENSIONS + TAR_EXTENSIONS


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


def split_archive_path(path: str) -> tuple[str, str] | None:
    """If path refers to a file or folder inside an archive, returns (archive_path, inner_path)."""
    lower = path.lower()
    if not any(ext in lower for ext in ARCHIVE_EXTENSIONS):
        return None

    if ":" in path and "://" not in path:
        parts = path.split(":", 1)
        if os.path.isfile(parts[0]) and is_archive_file(parts[0]):
            return parts[0], parts[1].strip("/")

    curr = path
    parts = []
    while True:
        parent, name = os.path.split(curr)
        if not name or parent == curr:
            break
        parts.append(name)
        curr = parent
        if os.path.isfile(curr) and is_archive_file(curr):
            inner = "/".join(reversed(parts)).strip("/")
            return curr, inner
    return None


def _inspect_archive(
    path: str,
    max_entries: int,
    start_line: int | None = None,
    end_line: int | None = None,
    subpath: str | None = None,
) -> ToolResult:
    import tarfile
    import zipfile

    lower = path.lower()
    dirs: set[str] = set()
    files: list[str] = []
    prefix = (subpath.strip("/") + "/") if subpath else None

    try:
        if any(lower.endswith(ext) for ext in ZIP_EXTENSIONS):
            with zipfile.ZipFile(path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if not name or "__MACOSX" in name or os.path.basename(name).startswith("._"):
                        continue
                    if prefix:
                        if not name.startswith(prefix) or name == prefix:
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
                    if prefix:
                        if not name.startswith(prefix) or name == prefix:
                            continue
                    if member.isdir() or name.endswith("/"):
                        dirs.add(name.rstrip("/") + "/")
                    else:
                        files.append(f"{name} ({_format_entry_size(member.size)})")

        entries = sorted(dirs) + sorted(files)
        total_count = len(entries)
        header_path = f"{path}/{subpath.strip('/')}" if subpath else path
        if total_count == 0:
            content_str = f"[archive {header_path} | total 0]"
        elif start_line is not None and start_line > total_count:
            return ToolResult.error(
                "range",
                detail=f"start_line ({start_line}) exceeds entry count ({total_count}) in '{header_path}'. Total entries: {total_count} (range: 1..{total_count}).",
                name="read",
            )
        elif start_line is not None or end_line is not None:
            s = max(1, start_line) if start_line else 1
            e = min(total_count, end_line) if end_line else min(total_count, s + max_entries - 1)
            e = max(s, e)
            sliced = entries[s - 1 : e]
            body = "\n".join(sliced)
            content_str = f"[archive {header_path} | entries {s}..{e} of {total_count}]\n{body}"
        elif total_count > max_entries:
            body = "\n".join(entries[:max_entries])
            content_str = (
                f"[archive {header_path} | total {total_count} | truncated]\n"
                f"{body}\n"
                f"... [truncated | next read(path='{header_path}', start_line={max_entries + 1})]"
            )
        else:
            body = "\n".join(entries)
            content_str = f"[archive {header_path} | total {total_count}]\n{body}"

        return ToolResult.done(
            content=content_str,
            display=f"[archive {header_path} | total {total_count}]",
        )
    except Exception as e:
        return ToolResult.error("archive", detail=str(e), name=path)


def read_archive_member(
    archive_path: str,
    inner_path: str,
    max_entries: int = 60,
    start_line: int | None = None,
    end_line: int | None = None,
) -> tuple[list[str], int] | ToolResult:
    """Read lines of an inner file or inspect a subfolder from an archive."""
    import tarfile
    import zipfile

    from core.tools.utils import get_max_tool_payload_bytes

    lower = archive_path.lower()
    norm_inner = inner_path.replace("\\", "/").strip("/")

    try:
        if any(lower.endswith(ext) for ext in ZIP_EXTENSIONS):
            with zipfile.ZipFile(archive_path, "r") as zf:
                infolist = zf.infolist()
                target_info = None
                for info in infolist:
                    if info.filename.strip("/") == norm_inner:
                        target_info = info
                        break
                if not target_info:
                    for info in infolist:
                        if info.filename.strip("/").lower() == norm_inner.lower():
                            target_info = info
                            break

                is_dir_entry = target_info and (target_info.is_dir() or target_info.filename.endswith("/"))
                has_children = not target_info and any(
                    info.filename.strip("/").startswith(norm_inner + "/") for info in infolist
                )
                if is_dir_entry or has_children:
                    return _inspect_archive(
                        archive_path,
                        max_entries=max_entries,
                        start_line=start_line,
                        end_line=end_line,
                        subpath=norm_inner,
                    )

                if not target_info:
                    return ToolResult.error(
                        "not_found",
                        detail=f"'{inner_path}' not found in archive '{archive_path}'",
                        name=inner_path,
                    )

                max_bytes = get_max_tool_payload_bytes()
                if target_info.file_size > max_bytes:
                    return ToolResult.error(
                        "size_exceeded",
                        detail=f"entry size {target_info.file_size} exceeds payload limit",
                        name=inner_path,
                    )

                raw_bytes = zf.read(target_info)
        else:
            with tarfile.open(archive_path, "r:*") as tf:
                members = tf.getmembers()
                target_member = None
                for member in members:
                    if member.name.strip("/") == norm_inner:
                        target_member = member
                        break
                if not target_member:
                    for member in members:
                        if member.name.strip("/").lower() == norm_inner.lower():
                            target_member = member
                            break

                is_dir_entry = target_member and (target_member.isdir() or target_member.name.endswith("/"))
                has_children = not target_member and any(
                    m.name.strip("/").startswith(norm_inner + "/") for m in members
                )
                if is_dir_entry or has_children:
                    return _inspect_archive(
                        archive_path,
                        max_entries=max_entries,
                        start_line=start_line,
                        end_line=end_line,
                        subpath=norm_inner,
                    )

                if not target_member:
                    return ToolResult.error(
                        "not_found",
                        detail=f"'{inner_path}' not found in archive '{archive_path}'",
                        name=inner_path,
                    )

                max_bytes = get_max_tool_payload_bytes()
                if target_member.size > max_bytes:
                    return ToolResult.error(
                        "size_exceeded",
                        detail=f"entry size {target_member.size} exceeds payload limit",
                        name=inner_path,
                    )

                extracted = tf.extractfile(target_member)
                if extracted is None:
                    return ToolResult.error(
                        "read",
                        detail=f"unable to extract '{inner_path}' from archive",
                        name=inner_path,
                    )
                raw_bytes = extracted.read()

        text = raw_bytes.decode("utf-8", errors="replace")
        lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
        return lines, len(lines)
    except Exception as e:
        return ToolResult.error("archive_read", detail=str(e), name=f"{archive_path}/{inner_path}")
