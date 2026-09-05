import re


def parse_numstat(output: str) -> tuple[int, int, list[str]]:
    """Parses `git diff --numstat` output into (added, deleted, changed_files)."""
    added, deleted = 0, 0
    changed_files: list[str] = []
    for line in output.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) >= 3:
            raw_path = parts[2].strip()
            if raw_path.startswith('"') and raw_path.endswith('"'):
                raw_path = raw_path[1:-1]
            if parts[0].isdigit() and parts[1].isdigit():
                added += int(parts[0])
                deleted += int(parts[1])
                changed_files.append(raw_path)
            elif parts[0] == "-" and parts[1] == "-":
                # Binary file change (e.g. images, compiled assets)
                added += 1
                changed_files.append(raw_path)
    return added, deleted, changed_files


def split_git_diff(diff_output: str) -> list[tuple[str, str, int, int]]:
    """Splits full unified git diff into per-file chunks: (file_path, diff_text, added, deleted)."""
    if not diff_output or not diff_output.strip():
        return []

    chunks = re.split(r"(?=^diff --git )", diff_output.strip(), flags=re.MULTILINE)
    results: list[tuple[str, str, int, int]] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        file_path = ""
        match = re.search(r"^diff --git a/(.*?) b/(.*)$", chunk, re.MULTILINE)
        if match:
            file_path = match.group(2)
        else:
            plus_match = re.search(r"^\+\+\+ b/(.*)$", chunk, re.MULTILINE)
            if plus_match:
                file_path = plus_match.group(1)
            else:
                minus_match = re.search(r"^--- a/(.*)$", chunk, re.MULTILINE)
                file_path = minus_match.group(1) if minus_match else "unknown"

        if file_path.startswith('"') and file_path.endswith('"'):
            file_path = file_path[1:-1]

        added = 0
        deleted = 0
        in_hunk = False
        for line in chunk.splitlines():
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deleted += 1

        results.append((file_path, chunk, added, deleted))
    return results
