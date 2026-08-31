"""Edge-case tests for tools/read.py ReadTool.

Focus: malformed inputs, binary/encoding, symlinks, traversal, path handling,
line-window edge cases. These complement (do not duplicate) test_read_tool.py.
"""
import os
import stat

import pytest

from tools.read import ReadTool


@pytest.fixture
def ctx(tmp_path):
    from tools.context import ToolContext

    return ToolContext(cwd=str(tmp_path))


def wb(root, name, data: bytes):
    p = os.path.join(root, name)
    os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(p) != root else None
    with open(p, "wb") as f:
        f.write(data)
    return p


# ---------------------------------------------------------------------------
# File content edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_binary_file_with_null_bytes(tmp_path, ctx):
    """Null bytes in a text file should not crash; decode with errors='replace'."""
    p = wb(tmp_path, "bin.dat", b"abc\x00\x00def\xff\nsecond\n")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_invalid_utf8_replaces_instead_of_crashing(tmp_path, ctx):
    """Invalid UTF-8 (0xFF) must not raise; uses errors='replace' on the tail path."""
    p = wb(tmp_path, "bad.txt", b"line one\n\xff\xfe\xfd\nline two\n")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_invalid_utf8_with_line_window(tmp_path, ctx):
    """Invalid UTF-8 when a line window is requested (byte rstrip + decode)."""
    p = wb(tmp_path, "bad2.txt", b"a\n\xff\xfe\nb\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 1, "end_line": 3}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_empty_file(tmp_path, ctx):
    p = wb(tmp_path, "empty.txt", b"")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "empty file" in res or "0 lines" in res, res


@pytest.mark.asyncio
async def test_empty_file_with_line_window(tmp_path, ctx):
    p = wb(tmp_path, "empty2.txt", b"")
    res = str(await ReadTool().execute({"path": p, "start_line": 1, "end_line": 5}, ctx=ctx))
    assert "empty file" in res or "0 lines" in res, res


@pytest.mark.asyncio
async def test_file_no_trailing_newline_counts_as_line(tmp_path, ctx):
    p = wb(tmp_path, "nonl.txt", b"only one line")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "of 1" in res or "1 line" in res or "Lines 1-1 of 1" in res, res


@pytest.mark.asyncio
async def test_huge_file_rejected(tmp_path, ctx, monkeypatch):
    """File larger than the payload cap must be rejected before reading."""
    from tools import read

    monkeypatch.setattr(read, "get_max_tool_payload_bytes", lambda: 100)
    p = wb(tmp_path, "big.txt", b"x" * 1000)
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "ERR:" in res
    assert "exceeds" in res


@pytest.mark.asyncio
async def test_oversized_read_request_returns_without_crash(tmp_path, ctx):
    """start_line beyond file should produce an ERR: range, not an IndexError."""
    p = wb(tmp_path, "small.txt", b"a\nb\nc\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 999}, ctx=ctx))
    assert "ERR:" in res, res


@pytest.mark.asyncio
async def test_start_line_exceeds_total_single_line_file(tmp_path, ctx):
    p = wb(tmp_path, "one.txt", b"single line no newline")
    res = str(await ReadTool().execute({"path": p, "start_line": 5}, ctx=ctx))
    assert "ERR:" in res, res


# ---------------------------------------------------------------------------
# Symlinks / hard links
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_symlink_resolves_to_target(tmp_path, ctx):
    target = wb(tmp_path, "real.txt", b"symlink content\n")
    link = os.path.join(tmp_path, "link.txt")
    os.symlink(target, link)
    res = str(await ReadTool().execute({"path": link}, ctx=ctx))
    assert "symlink content" in res


@pytest.mark.asyncio
async def test_symlink_to_outside_dir(tmp_path, ctx):
    """A symlink pointing outside the cwd still resolves (tool has no sandbox)."""
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("secret\n")
    link = os.path.join(tmp_path, "esc.txt")
    try:
        os.symlink(str(outside), link)
    except OSError:
        pytest.skip("symlink not permitted")
    res = str(await ReadTool().execute({"path": link}, ctx=ctx))
    assert "secret" in res


@pytest.mark.asyncio
async def test_hard_link_shares_content(tmp_path, ctx):
    p = wb(tmp_path, "orig.txt", b"hard link data\n")
    hlink = os.path.join(tmp_path, "hard.txt")
    os.link(p, hlink)
    res = str(await ReadTool().execute({"path": hlink}, ctx=ctx))
    assert "hard link data" in res


@pytest.mark.asyncio
async def test_broken_symlink(tmp_path, ctx):
    link = os.path.join(tmp_path, "broken.txt")
    try:
        os.symlink(os.path.join(tmp_path, "does_not_exist"), link)
    except OSError:
        pytest.skip("symlink not permitted")
    res = str(await ReadTool().execute({"path": link}, ctx=ctx))
    assert "ERR:" in res


# ---------------------------------------------------------------------------
# Path handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relative_path_resolves_against_cwd(ctx, tmp_path):
    wb(tmp_path, "rel.txt", b"relative resolved\n")
    res = str(await ReadTool().execute({"path": "rel.txt"}, ctx=ctx))
    assert "relative resolved" in res


@pytest.mark.asyncio
async def test_dotdot_traversal_reads_file(tmp_path, ctx):
    """../ traversal is resolved by os.path.realpath; tool follows it."""
    wb(tmp_path.parent, "outside.txt", b"traversed\n")
    res = str(await ReadTool().execute({"path": "../outside.txt"}, ctx=ctx))
    assert "traversed" in res


@pytest.mark.asyncio
async def test_path_with_spaces(ctx, tmp_path):
    p = wb(tmp_path, "my file here.txt", b"spaces ok\n")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "spaces ok" in res


@pytest.mark.asyncio
async def test_path_with_unicode_and_cyrillic(ctx, tmp_path):
    p = wb(tmp_path, "файл \u2014 數據.txt", "кириллица юникод\n".encode("utf-8"))
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "кириллица юникод" in res


@pytest.mark.skipif(os.name == "nt", reason="quotes are invalid in Windows filenames")
@pytest.mark.asyncio
async def test_path_with_quotes_and_escaped(ctx, tmp_path):
    p = wb(tmp_path, 'quo"te\\ name.txt', b"quotes\n")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "quotes" in res


@pytest.mark.asyncio
async def test_directory_path_returns_listing(tmp_path, ctx):
    os.makedirs(os.path.join(tmp_path, "adir"), exist_ok=True)
    res = str(await ReadTool().execute({"path": os.path.join(tmp_path, "adir")}, ctx=ctx))
    assert "[dir " in res or "is a directory" in res


@pytest.mark.asyncio
async def test_permission_denied(tmp_path, ctx):
    if os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0:
        pytest.skip("no permission semantics on this platform/root")
    p = wb(tmp_path, "noperm.txt", b"secret\n")
    os.chmod(p, 0)
    try:
        res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    finally:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    assert "ERR:" in res


@pytest.mark.asyncio
async def test_absolute_path_outside_cwd(tmp_path, ctx):
    outside = tmp_path.parent / "abs_secret.txt"
    outside.write_text("abs read\n")
    res = str(await ReadTool().execute({"path": str(outside)}, ctx=ctx))
    assert "abs read" in res


@pytest.mark.asyncio
async def test_expanduser_tilde(tmp_path, ctx, monkeypatch):
    # Redirect HOME into tmp: the test only proves that "~" in a requested
    # path expands to the user's home, and writing the real home directory is
    # neither necessary nor allowed under sandboxed runs.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    p = os.path.join(str(tmp_path), ".johnston_read_test_tmp.txt")
    with open(p, "w") as f:
        f.write("tilde read\n")
    res = str(await ReadTool().execute({"path": "~/.johnston_read_test_tmp.txt"}, ctx=ctx))
    assert "tilde read" in res


@pytest.mark.asyncio
async def test_etc_passwd_readable(tmp_path, ctx):
    """Reading /etc/hosts (usually world-readable) should work regardless of cwd."""
    if not os.path.exists("/etc/hosts"):
        pytest.skip("no /etc/hosts")
    res = str(await ReadTool().execute({"path": "/etc/hosts"}, ctx=ctx))
    assert "ERR:" not in res


# ---------------------------------------------------------------------------
# Argument edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_path(tmp_path, ctx):
    res = str(await ReadTool().execute({}, ctx=ctx))
    # path resolves to cwd (a directory) -> directory listing, not a crash
    assert "ERR: listing" not in res


@pytest.mark.asyncio
async def test_path_none(tmp_path, ctx):
    res = str(await ReadTool().execute({"path": None}, ctx=ctx))
    assert "ERR: listing" not in res


@pytest.mark.asyncio
async def test_path_non_string(tmp_path, ctx):
    res = str(await ReadTool().execute({"path": 12345}, ctx=ctx))
    assert isinstance(res, str)


@pytest.mark.asyncio
async def test_extra_unknown_keys_ignored(tmp_path, ctx):
    p = wb(tmp_path, "extra.txt", b"extra keys\n")
    res = str(await ReadTool().execute({"path": p, "bogus": 1, "wat": "x"}, ctx=ctx))
    assert "extra keys" in res


@pytest.mark.asyncio
async def test_start_end_inverted(tmp_path, ctx):
    """end_line < start_line: window math must not crash."""
    p = wb(tmp_path, "inv.txt", b"1\n2\n3\n4\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 4, "end_line": 1}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_start_negative(tmp_path, ctx):
    p = wb(tmp_path, "neg.txt", b"a\nb\nc\n")
    res = str(await ReadTool().execute({"path": p, "start_line": -5}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_start_end_beyond_file(tmp_path, ctx):
    p = wb(tmp_path, "beyond.txt", b"a\nb\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 1, "end_line": 500}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_end_none_with_start(tmp_path, ctx):
    p = wb(tmp_path, "endnone.txt", b"l1\nl2\nl3\nl4\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 2, "end_line": None}, ctx=ctx))
    assert "l2" in res


@pytest.mark.asyncio
async def test_start_end_as_strings(tmp_path, ctx):
    p = wb(tmp_path, "str.txt", b"a\nb\nc\n")
    res = str(await ReadTool().execute({"path": p, "start_line": "2", "end_line": "3"}, ctx=ctx))
    assert "b" in res and "c" in res


@pytest.mark.asyncio
async def test_start_as_float(tmp_path, ctx):
    p = wb(tmp_path, "float.txt", b"a\nb\nc\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 2.7}, ctx=ctx))
    # try_int(2.7) -> int(2.7)=2; should not crash
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_start_as_non_numeric_string(tmp_path, ctx):
    p = wb(tmp_path, "nonum.txt", b"a\nb\nc\n")
    res = str(await ReadTool().execute({"path": p, "start_line": "abc"}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_start_huge_integer(tmp_path, ctx):
    p = wb(tmp_path, "huge.txt", b"a\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 10**30}, ctx=ctx))
    assert "ERR:" in res


@pytest.mark.asyncio
async def test_content_offset_beyond_eof(tmp_path, ctx):
    """content_offset past EOF -> empty window; must not IndexError in pagination."""
    p = wb(tmp_path, "off.txt", b"0123456789")
    res = str(await ReadTool().execute({"path": p, "content_offset": 5000}, ctx=ctx))
    assert "ERR:" not in res, res


@pytest.mark.asyncio
async def test_content_offset_negative_clamped(tmp_path, ctx):
    p = wb(tmp_path, "off2.txt", b"0123456789")
    res = str(await ReadTool().execute({"path": p, "content_offset": -100}, ctx=ctx))
    assert "0123456789" in res


@pytest.mark.asyncio
async def test_content_offset_zero(tmp_path, ctx):
    p = wb(tmp_path, "off3.txt", b"0000000000")
    res = str(await ReadTool().execute({"path": p, "content_offset": 0}, ctx=ctx))
    assert "0000000000" in res


# ---------------------------------------------------------------------------
# Line numbering with non-ASCII / CRLF
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crlf_line_ending(tmp_path, ctx):
    p = wb(tmp_path, "crlf.txt", b"west\r\nwe are\r\none\r\n")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "we are" in res


@pytest.mark.asyncio
async def test_crlf_with_line_window(tmp_path, ctx):
    p = wb(tmp_path, "crlf2.txt", b"a\r\nb\r\nc\r\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 2, "end_line": 2}, ctx=ctx))
    assert "b" in res


@pytest.mark.asyncio
async def test_non_ascii_line_window(tmp_path, ctx):
    p = wb(tmp_path, "uni.txt", b"\xd0\xba\xd1\x96\xd1\x80\xd0\xb8\n\xe4\xb8\xad\xe6\x96\x87\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 2, "end_line": 2}, ctx=ctx))
    assert "\u4e2d\u6587" in res


# ---------------------------------------------------------------------------
# Output / truncation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_line_window_only_returns_requested_lines(tmp_path, ctx):
    p = wb(tmp_path, "win.txt", b"l1\nl2\nl3\nl4\nl5\n")
    res = str(await ReadTool().execute({"path": p, "start_line": 3, "end_line": 4}, ctx=ctx))
    assert "l3" in res
    assert "l4" in res
    assert "l1" not in res


@pytest.mark.asyncio
async def test_end_line_gt_total_shows_all(tmp_path, ctx):
    p = wb(tmp_path, "gt.txt", b"x\ny\n")
    res = str(await ReadTool().execute({"path": p, "end_line": 100}, ctx=ctx))
    assert "x" in res and "y" in res


@pytest.mark.asyncio
async def test_single_line_file_read(tmp_path, ctx):
    p = wb(tmp_path, "one2.txt", b"just a single line")
    res = str(await ReadTool().execute({"path": p}, ctx=ctx))
    assert "just a single line" in res
