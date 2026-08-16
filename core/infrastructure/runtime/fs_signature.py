"""Filesystem signature helpers for Johnston.

Provides cheap (path, mtime_ns, size) directory scans used by caching layers
(roles, rules, skills, sessions) to detect external changes without re-reading
file contents.
"""

import os
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple, Union


@dataclass(frozen=True)
class SignatureEntry:
    """A single ``(path, mtime_ns, size)`` filesystem signature entry.

    ``mtime_ns`` and ``size`` are what callers actually consume for caching.
    The path is kept for stable ordering, not compared for equality.
    """

    path: str
    mtime_ns: int
    size: int


def compute_dir_signature(
    dirs: Sequence[Union[str, Tuple[str, object]]],
    extensions: Optional[Sequence[str]] = None,
) -> Optional[Tuple[SignatureEntry, ...]]:
    """Collects ``SignatureEntry`` for files under ``dirs``.

    - Only files whose name ends with one of ``extensions`` are included
      (when ``extensions`` is None every file is included).
    - Directories are scanned non-recursively with ``sorted(os.listdir)``.
    - Missing directories and per-directory OSErrors are skipped.
    - Returns None when no matching entries were found (so callers can treat
      an empty signature the same as "no data on disk").
    """
    if extensions:
        suffixes = tuple(ext.encode() if isinstance(ext, bytes) else ext for ext in extensions)
    else:
        suffixes = None

    entries: List[SignatureEntry] = []
    for dpath, *_rest in dirs:
        if not os.path.isdir(dpath):
            continue
        try:
            for fname in sorted(os.listdir(dpath)):
                if suffixes and not fname.endswith(suffixes):
                    continue
                fpath = os.path.join(dpath, fname)
                if not os.path.isfile(fpath):
                    continue
                st = os.stat(fpath)
                entries.append(SignatureEntry(fpath, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return tuple(entries) if entries else None


def compute_dir_signature_hash(
    dirs: Sequence[str],
    extensions: Optional[Sequence[str]] = None,
) -> Optional[int]:
    """XOR-hash of (path, mtime_ns, size) for files under non-recursive ``dirs``.

    Used when only a cheap equality check is needed (sessions cache) instead
    of retaining the full entry list. Returns None when no entries exist.
    """
    signature = compute_dir_signature(dirs, extensions)
    if signature is None:
        return None
    acc = 0
    for entry in signature:
        acc ^= hash((entry.path, entry.mtime_ns, entry.size))
    return acc


def compute_dir_signature_recursive(
    dirs: Sequence[str],
    filenames: Optional[Sequence[str]] = None,
    skip_dir: Optional[Callable[[str], bool]] = None,
) -> Tuple[SignatureEntry, ...]:
    """Collects (path, mtime_ns, size) for files under ``dirs`` recursively.

    Unlike :func:`compute_dir_signature`, this walks each tree with
    ``os.walk`` (so nested subdirectories are traversed) and matches against
    full base filenames (e.g. ``SKILL.md``) rather than extensions.

    ``skip_dir`` filters visited subdirectory basenames (e.g. ignoring
    dot-directories and VCS dirs). Returns an empty tuple when nothing matched.
    """
    names = set(filenames) if filenames else None
    entries: List[SignatureEntry] = []
    for dpath in dirs:
        if not os.path.isdir(dpath):
            continue
        try:
            for root, subdirs, files in os.walk(dpath):
                if skip_dir:
                    subdirs[:] = [d for d in subdirs if not skip_dir(d)]
                for f in files:
                    if names and f not in names:
                        continue
                    fpath = os.path.join(root, f)
                    try:
                        st = os.stat(fpath)
                    except OSError:
                        continue
                    entries.append(SignatureEntry(fpath, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return tuple(entries)
