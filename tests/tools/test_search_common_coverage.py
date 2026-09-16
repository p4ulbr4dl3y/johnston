"""Coverage-focused unit tests for ``johnston.core.tools.search.common``.

Exercises error paths, glob edge cases, gitignore stat fingerprinting and
walk filtering that the integration-level suite
(``tests/tools/test_search_tool.py``) leaves uncovered.
"""

import os
import re
import sys
import threading
from unittest.mock import patch

import pytest

import johnston.core.tools.search.common as common_mod
from johnston.core.tools.search.common import (
    MAX_SEARCH_FILE_BYTES,
    _clear_gitignore_matcher_cache,
    _gitignore_entries,
    _GitignoreMatcher,
    _glob_to_regex,
    _load_gitignore_spec,
    _match_glob,
    _safe_relpath,
    _walk_filtered,
    _walk_filtered_list,
    compute_line_offsets,
    get_line_number,
    get_max_search_bytes,
    is_binary_file,
)


@pytest.fixture(autouse=True)
def _clear_gitignore_cache():
    _clear_gitignore_matcher_cache()
    yield
    _clear_gitignore_matcher_cache()


class _SetEventMatcher:
    """Minimal duck-typed gitignore matcher that sets a threading event."""

    def __init__(self, event: threading.Event, root: str):
        self._event = event
        self._root = root

    def is_ignored(self, rel_path: str) -> bool:
        self._event.set()
        return False


# --- get_max_search_bytes -------------------------------------------------


def test_get_max_search_bytes_returns_payload_limit():
    with patch(
        "johnston.core.tools.search.common.get_max_tool_payload_bytes",
        return_value=12_345,
    ):
        assert get_max_search_bytes() == 12_345


def test_get_max_search_bytes_falls_back_on_error():
    with patch(
        "johnston.core.tools.search.common.get_max_tool_payload_bytes",
        side_effect=RuntimeError("boom"),
    ):
        assert get_max_search_bytes() == MAX_SEARCH_FILE_BYTES


# --- _safe_relpath --------------------------------------------------------


def test_safe_relpath_strips_dot_prefix(tmp_path):
    assert _safe_relpath(os.path.join(tmp_path, "a.py"), str(tmp_path)) == "a.py"


def test_safe_relpath_returns_path_on_error():
    with patch("os.path.relpath", side_effect=ValueError("cross-device")):
        assert _safe_relpath(r"C:\data\a.py", "D:\\other") == "C:/data/a.py"


# --- is_binary_file -------------------------------------------------------


def test_is_binary_file_null_byte_in_first_chunk(tmp_path):
    p = tmp_path / "mixed.dat"
    p.write_bytes(b"text\x00more")
    assert is_binary_file(str(p)) is True


def test_is_binary_file_unreadable_returns_true(tmp_path):
    p = tmp_path / "locked.txt"
    p.write_text("hello")
    with patch("builtins.open", side_effect=PermissionError("denied")):
        assert is_binary_file(str(p)) is True


# --- line offset helpers --------------------------------------------------


def test_compute_line_offsets_and_get_line_number():
    assert compute_line_offsets("no newline") == [0]
    assert get_line_number([0], 4) == 1
    offsets = compute_line_offsets("ab\ncd\nef")
    assert offsets == [0, 3, 6]
    assert get_line_number(offsets, 0) == 1
    assert get_line_number(offsets, 2) == 1
    assert get_line_number(offsets, 3) == 2
    assert get_line_number(offsets, 5) == 2
    assert get_line_number(offsets, 6) == 3


# --- _glob_to_regex edge cases -------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "matching", "non_matching"),
    [
        ("**", ["a", "b/c", "d/e/f"], ["x\ny"]),
        ("a**b", ["ab", "a/b", "a/x/b"], ["xa", "b/a"]),
        ("?", ["x", "y"], ["xy", "a/b"]),
        ("[abc]", ["a", "b", "c"], ["d", "ab"]),
        ("[!abc]", ["d", "x"], ["a", "b", "c"]),
        ("[]]", ["]"], ["a"]),
        ("a.b", ["a.b"], ["axb"]),
        ("+(x)", ["+(x)"], ["xx"]),
    ],
)
def test_glob_to_regex_edge_cases(pattern, matching, non_matching):
    regex = _glob_to_regex(pattern)
    for candidate in matching:
        assert regex.fullmatch(candidate), f"{pattern!r} should match {candidate!r}"
    for candidate in non_matching:
        assert not regex.fullmatch(candidate), f"{pattern!r} should NOT match {candidate!r}"


def test_glob_to_regex_invalid_bracket_range_raises():
    with pytest.raises(re.error):
        _glob_to_regex("[z-a]")


def test_glob_to_regex_unclosed_bracket_literal():
    regex = _glob_to_regex("a[b")
    assert regex.fullmatch("a[b")
    assert not regex.fullmatch("ac")


def test_glob_to_regex_double_star_slash():
    regex = _glob_to_regex("**/*.py")
    assert regex.fullmatch("x/y.py")
    assert regex.fullmatch("main.py")
    assert not regex.fullmatch("x.py.bak")


# --- _match_glob branches -------------------------------------------------


def test_match_glob_missing_pattern_matches_everything():
    assert _match_glob("anything/file.txt", "file.txt", None) is True


def test_match_glob_strips_dot_prefix():
    assert _match_glob("./src/a.py", "a.py", "*.py") is True


def test_match_glob_negation_via_real_re_error():
    # '[z-a]' fails to compile as regex (bad character range) -> fnmatch fallback
    assert _match_glob("keep.txt", "keep.txt", "![z-a]") is True
    assert _match_glob("keep.txt", "keep.txt", "[z-a]") is False
    assert _match_glob("keep.txt", "keep.txt", "[z-a]*.py") is False


def test_match_glob_fnmatch_fallback(monkeypatch):
    def _boom(_pattern):
        raise re.error("bad pattern")

    monkeypatch.setattr(common_mod, "_glob_to_regex", _boom)
    # Negative fallback match wins
    assert _match_glob("keep.txt", "keep.txt", "!keep.txt") is False
    assert _match_glob("other.txt", "other.txt", "!keep.txt") is True
    # Positive fallback match wins
    assert _match_glob("sub/keep.txt", "keep.txt", "keep.*") is True
    assert _match_glob("sub/other.txt", "other.txt", "keep.*") is False
    # Negative-only pattern with no positive patterns
    assert _match_glob("sub/a.py", "a.py", "!*.log") is True


# --- _GitignoreMatcher ----------------------------------------------------


def test_gitignore_matcher_prefixed_patterns(tmp_path):
    (tmp_path / ".gitignore").write_text("sub/*.tmp\n")
    matcher = _GitignoreMatcher.load_from_root(str(tmp_path))
    assert matcher is not None
    assert matcher.is_ignored("sub/a.tmp") is True
    assert matcher.is_ignored("sub/deep/a.tmp") is False
    assert matcher.is_ignored("root.tmp") is False


def test_gitignore_matcher_escaped_metacharacters():
    matcher = _GitignoreMatcher([("", r"a.b+c"), ("", r"^caret$")], "/tmp")
    assert matcher.is_ignored("a.b+c") is True
    assert matcher.is_ignored("axbxc") is False
    assert matcher.is_ignored("^caret$") is True
    assert matcher.is_ignored("caret") is False


def test_gitignore_matcher_bad_pattern_skipped():
    matcher = _GitignoreMatcher([("", "[z-a]")], "/tmp")
    assert matcher._compiled == []


def test_gitignore_matcher_is_ignored_dir_only():
    matcher = _GitignoreMatcher([("", "build/")], "/tmp")
    assert matcher.is_ignored("build/x/y.txt") is True
    assert matcher.is_ignored("build/") is True
    assert matcher.is_ignored("build") is False
    assert matcher.is_ignored("rebuild.txt") is False


def test_gitignore_matcher_normalizes_windows_paths():
    matcher = _GitignoreMatcher([("", "*.log")], "/tmp")
    assert matcher.is_ignored(r"sub\\app.log") is True
    assert matcher.is_ignored("./sub/app.log") is True


def test_gitignore_matcher_prefix_negation():
    matcher = _GitignoreMatcher([("", "sub/*.tmp"), ("", "!sub/keep.tmp")], "/tmp")
    assert matcher.is_ignored("sub/a.tmp") is True
    assert matcher.is_ignored("sub/keep.tmp") is False
    assert matcher.is_ignored("root.tmp") is False


def test_gitignore_matcher_double_star_no_slash():
    matcher = _GitignoreMatcher([("", "ab**")], "/tmp")
    assert matcher.is_ignored("abx") is True
    assert matcher.is_ignored("xab") is False
    assert matcher.is_ignored("a/b") is False


def test_gitignore_matcher_question_mark():
    matcher = _GitignoreMatcher([("", "sub/?olo.txt")], "/tmp")
    assert matcher.is_ignored("sub/holo.txt") is True
    assert matcher.is_ignored("sub/olo.txt") is False


def test_gitignore_matcher_bracket_negation():
    matcher = _GitignoreMatcher([("", "sub/[!a].py")], "/tmp")
    assert matcher.is_ignored("sub/b.py") is True
    assert matcher.is_ignored("sub/a.py") is False


def test_gitignore_matcher_bracket_leading_bang():
    """'[!]' -> bang + leading ']' skipped, unclosed -> literal '[' (lines 333-336, 349)."""
    matcher = _GitignoreMatcher([("", "[!]")], "/tmp")
    assert len(matcher._compiled) == 1
    assert matcher.is_ignored("[!]") is True
    assert matcher.is_ignored("]") is False
    assert matcher.is_ignored("a") is False


def test_gitignore_matcher_unclosed_bracket_literal():
    """Unclosed '[' escapes to a literal (line 349)."""
    matcher = _GitignoreMatcher([("", "sub/a[b")], "/tmp")
    assert matcher.is_ignored("sub/a[b") is True
    assert matcher.is_ignored("sub/axb") is False


# --- _load_gitignore_spec / _gitignore_entries ----------------------------


def test_load_gitignore_spec_skips_comments_and_blank_lines(tmp_path):
    (tmp_path / ".gitignore").write_text("# comment\n\n*.log\n")
    matcher = _load_gitignore_spec(str(tmp_path))
    assert matcher is not None
    assert matcher.is_ignored("app.log") is True
    assert matcher.is_ignored("app.txt") is False


def test_load_gitignore_spec_none_without_gitignore(tmp_path):
    assert _load_gitignore_spec(str(tmp_path)) is None
    assert _load_gitignore_spec(str(tmp_path / "missing")) is None


def test_load_gitignore_spec_ignores_unreadable_file(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n")
    with patch("builtins.open", side_effect=OSError("denied")):
        assert _load_gitignore_spec(str(tmp_path)) is None


def test_load_gitignore_spec_anchored_and_dir_only(tmp_path):
    (tmp_path / ".gitignore").write_text("/top.txt\nlogs/\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".gitignore").write_text("local.txt\n")
    matcher = _load_gitignore_spec(str(tmp_path))
    assert matcher is not None
    assert matcher.is_ignored("top.txt") is True
    assert matcher.is_ignored("sub/top.txt") is False
    assert matcher.is_ignored("logs/out.log") is True
    assert matcher.is_ignored("sub/local.txt") is True
    assert matcher.is_ignored("local.txt") is False


def test_gitignore_entries_missing_root(tmp_path):
    assert _gitignore_entries(str(tmp_path / "nope" / "deeper")) == ()


def test_gitignore_entries_fingerprint(tmp_path):
    (tmp_path / ".gitignore").write_bytes(b"*.log\n")
    entries = _gitignore_entries(str(tmp_path))
    assert len(entries) == 1
    path, mtime_ns, size = entries[0]
    assert path == str(tmp_path / ".gitignore")
    assert mtime_ns > 0
    assert size == len(b"*.log\n")


def test_gitignore_entries_empty_root_falls_back(tmp_path):
    assert _gitignore_entries(str(tmp_path)) == (("", 0, 0),)


def test_gitignore_entries_stat_error_skipped(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\n")
    orig_stat = os.stat

    def _stat(path, *args, **kwargs):
        if str(path).endswith(".gitignore"):
            raise OSError("gone")
        return orig_stat(path, *args, **kwargs)

    with patch("os.stat", side_effect=_stat):
        assert _gitignore_entries(str(tmp_path)) == (("", 0, 0),)


# --- _walk_filtered -------------------------------------------------------


def test_walk_filtered_cancel_event_precheck(tmp_path):
    (tmp_path / "a.py").write_text("pass\n")
    event = threading.Event()
    event.set()
    assert list(_walk_filtered(str(tmp_path), cancel_event=event)) == []


def test_walk_filtered_cancel_during_file_loop(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_text("pass\n")
    (tmp_path / "root.py").write_text("pass\n")
    event = threading.Event()
    matcher = _SetEventMatcher(event, str(tmp_path))
    files = list(
        _walk_filtered(str(tmp_path), gitignore_matcher=matcher, cancel_event=event)
    )
    assert files == []


def test_walk_filtered_file_target_uses_dirname(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("pass\n")
    assert list(_walk_filtered(str(f))) == []


@pytest.mark.skipif(sys.platform == "win32", reason="os.mkfifo is POSIX-only")
def test_walk_filtered_hidden_and_special_files(tmp_path):
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "h.py").write_text("pass\n")
    (tmp_path / ".dotfile").write_text("x\n")
    (tmp_path / "normal.py").write_text("pass\n")
    (tmp_path / "sub.py").write_text("pass\n")
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    names = {os.path.basename(f) for f in _walk_filtered_list(str(tmp_path))}
    assert names == {"normal.py", "sub.py"}
    assert ".dotfile" not in names

    names_hidden = {
        os.path.basename(f) for f in _walk_filtered_list(str(tmp_path), include_hidden=True)
    }
    assert ".dotfile" in names_hidden
    assert ".hidden" not in names_hidden  # directories are never yielded


def test_walk_filtered_excluded_and_hidden_dirs(tmp_path):
    for name in ("node_modules", "pkg.egg-info", ".git_meta", "keepdir"):
        (tmp_path / name).mkdir()
    (tmp_path / "keepdir" / "k.py").write_text("pass\n")
    (tmp_path / "node_modules" / "n.js").write_text("var x;\n")
    (tmp_path / "pkg.egg-info" / "PKG-INFO").write_text("y\n")
    (tmp_path / ".git_meta" / "g.py").write_text("pass\n")

    names = {os.path.basename(f) for f in _walk_filtered_list(str(tmp_path))}
    assert names == {"k.py"}


def test_walk_filtered_symlink_survives(tmp_path):
    target = tmp_path / "real.py"
    target.write_text("pass\n")
    os.symlink(str(target), str(tmp_path / "link.py"))
    names = {os.path.basename(f) for f in _walk_filtered_list(str(tmp_path))}
    assert names == {"real.py", "link.py"}


def test_walk_filtered_stat_error_skipped(tmp_path):
    (tmp_path / "a.py").write_text("pass\n")
    with patch("os.stat", side_effect=OSError("gone")):
        assert _walk_filtered_list(str(tmp_path)) == []


def test_walk_filtered_gitignore_skips(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.txt").write_text("x\n")
    (tmp_path / "app.log").write_text("x\n")
    (tmp_path / "keep.py").write_text("pass\n")
    (tmp_path / "keep2.py").write_text("pass\n")
    matcher = _GitignoreMatcher.load_from_root(str(tmp_path))
    assert matcher is not None
    files = _walk_filtered_list(str(tmp_path), gitignore_matcher=matcher)
    assert [os.path.basename(f) for f in files] == ["keep.py", "keep2.py"]


def test_walk_filtered_file_ignored_by_gitignore(tmp_path):
    """A file target whose relative path is ignored yields nothing (files loop)."""
    (tmp_path / ".gitignore").write_text("secret.py\n")
    (tmp_path / "secret.py").write_text("x = 1\n")
    matcher = _GitignoreMatcher.load_from_root(str(tmp_path))
    assert matcher is not None
    assert _walk_filtered_list(str(tmp_path), gitignore_matcher=matcher) == []


def test_walk_filtered_hidden_dot_dir_excluded(tmp_path):
    """Hidden dirs are skipped unless include_hidden (line 501)."""
    (tmp_path / ".secret_io").mkdir()
    (tmp_path / ".secret_io" / "vars.py").write_text("X=1\n")
    (tmp_path / "visible.py").write_text("pass\n")
    names = {os.path.basename(f) for f in _walk_filtered_list(str(tmp_path))}
    assert names == {"visible.py"}
    names_hidden = {
        os.path.basename(f)
        for f in _walk_filtered_list(str(tmp_path), include_hidden=True)
    }
    assert names_hidden == {"vars.py", "visible.py"}


@pytest.mark.skipif(sys.platform == "win32", reason="os.mkfifo is POSIX-only")
def test_walk_filtered_non_regular_file_skipped(tmp_path):
    """FIFO/socket targets are skipped (line 519)."""
    (tmp_path / "data.py").write_text("pass\n")
    os.mkfifo(str(tmp_path / "pipe.py"))
    names = {os.path.basename(f) for f in _walk_filtered_list(str(tmp_path))}
    assert names == {"data.py"}


def test_walk_filtered_dir_ignored_via_matcher(tmp_path):
    """Dirs ignored by the matcher do not get recursed (is_ignored 'dir/')."""
    (tmp_path / ".gitignore").write_text("vendor/\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "lib.py").write_text("pass\n")
    (tmp_path / "keep.py").write_text("pass\n")
    matcher = _GitignoreMatcher.load_from_root(str(tmp_path))
    assert matcher is not None
    files = _walk_filtered_list(str(tmp_path), gitignore_matcher=matcher)
    assert [os.path.basename(f) for f in files] == ["keep.py"]
