"""Edge-case tests for tools/edit.py and tools/create.py.

Goal is to find bugs (data loss, traversal, crashes on valid input).
Uses .txt extension everywhere to avoid the linter manager adding noise.
"""
import os
import stat
import sys
import tempfile
import unittest

import pytest

from tools.create import CreateTool
from tools.edit import EditTool, MultiEditTool, apply_chunk_replacements


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.old_cwd)
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, path, data, encoding="utf-8"):
        full = os.path.join(self.tmp, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        # newline="" keeps \r\n verbatim so CRLF fixtures are not doubled on Windows.
        with open(full, "w", encoding=encoding, newline="") as f:
            f.write(data)
        return full

    def read(self, path, encoding="utf-8"):
        with open(os.path.join(self.tmp, path), "r", encoding=encoding) as f:
            return f.read()


# ---------------------------------------------------------------------------
# edit: apply_chunk_replacements (pure function edge cases)
# ---------------------------------------------------------------------------
class TestApplyChunks(_Base):
    def test_empty_chunks_list_raises(self):
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements("abc\n", [], "dummy.txt")
        self.assertIn("no replacement chunks", str(ctx.exception))

    def test_chunk_without_old_str_raises(self):
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements("abc\n", [{"new_str": "x"}], "dummy.txt")
        self.assertIn("missing 'old_str'", str(ctx.exception))

    def test_chunk_without_new_str_raises(self):
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements("abc\n", [{"old_str": "abc"}], "dummy.txt")
        self.assertIn("missing 'new_str'", str(ctx.exception))

    def test_multiple_allow_multiple_replaces_all(self):
        new, _ = apply_chunk_replacements(
            "dup\ndup\ndup\n", [{"old_str": "dup", "new_str": "X", "allow_multiple": True}], "d.txt"
        )
        self.assertEqual(new, "X\nX\nX\n")

    def test_multiple_false_fails(self):
        with self.assertRaises(ValueError):
            apply_chunk_replacements("dup\ndup\n", [{"old_str": "dup", "new_str": "X"}], "d.txt")

    def test_inverted_start_end_does_not_crash(self):
        # start > end. Should not crash; exact behavior is unspecified but must not raise unexpected errors.
        try:
            new, _ = apply_chunk_replacements(
                "a\nb\nc\nd\n", [{"old_str": "c", "new_str": "C", "start_line": 4, "end_line": 2}], "d.txt"
            )
        except ValueError:
            # no crash is the requirement (a ValueError is acceptable for "not a clean match")
            return
        self.assertIn("C", new)

    def test_string_line_numbers_coerced(self):
        new, _ = apply_chunk_replacements(
            "a\nb\n", [{"old_str": "b", "new_str": "B", "start_line": "2", "end_line": "2"}], "d.txt"
        )
        self.assertIn("B", new)

    def test_negative_start_line_does_not_crash(self):
        try:
            apply_chunk_replacements(
                "a\nb\nc\n", [{"old_str": "b", "new_str": "B", "start_line": -5, "end_line": 2}], "d.txt"
            )
        except ValueError:
            return

    def test_multiline_unicode_target(self):
        content = "первая строка\nвторая строка\nтретья\n"
        new, _ = apply_chunk_replacements(
            content, [{"old_str": "вторая строка\nтретья", "new_str": "СРЕДНЯЯ\nТРЕТЬЯ"}], "d.txt"
        )
        self.assertIn("СРЕДНЯЯ", new)
        self.assertIn("ТРЕТЬЯ", new)

    def test_literal_backslash_newline_not_treated_as_newline(self):
        # target contains the two chars backslash+n, not an actual newline
        content = "a\\nb\n"
        new, _ = apply_chunk_replacements(content, [{"old_str": "a\\nb", "new_str": "averylong"}], "d.txt")
        self.assertEqual(new, "averylong\n")

    def test_very_long_target(self):
        token = "x" * 5000
        content = "start\n" + token + "\nend\n"
        new, _ = apply_chunk_replacements(content, [{"old_str": token, "new_str": "SHORT"}], "d.txt")
        self.assertNotIn(token, new)
        self.assertIn("SHORT", new)

    async def test_surrogate_new_str_via_tool_returns_err(self):
        # A lone surrogate cannot be encoded to UTF-8. Tool-level should return a
        # graceful error, not crash or write garbage.
        tool = EditTool()
        p = os.path.join(self.tmp, "surr.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("abc\n")
        res = str(await tool.execute({"path": p, "old_str": "abc", "new_str": "\ud800abc"}))
        self.assertIn("ERR:", res)
        # Original content must be unchanged (atomic write must not have fired).
        self.assertEqual(open(p, encoding="utf-8").read(), "abc\n")

    def test_single_curly_quote_style_preserved(self):
        # File has LEFT single curly quotes, old_str uses straight ones -> the
        # replacement's straight quotes become RIGHT single curly (has_single branch).
        new, _ = apply_chunk_replacements(
            "print(‘x’)\n", [{"old_str": "print('x')", "new_str": "print('y')"}], "d.txt"
        )
        self.assertEqual(new, "print(’y’)\n")

    def test_delete_crlf_line_consumes_newline(self):
        # Empty replacement in a CRLF file must swallow the \r\n so the whole
        # line disappears instead of leaving a dangling CR.
        new, _ = apply_chunk_replacements(
            "line1\r\nTOK\r\nline3\r\n", [{"old_str": "TOK", "new_str": ""}], "d.txt"
        )
        self.assertEqual(new, "line1\r\nline3\r\n")

    def test_whitespace_only_target_empty_hint(self):
        # target_lines strips to nothing -> fuzzy hint must be empty, error keeps
        # the bare "exact block not found" message (no "[Hint:" suffix).
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(
                "abc\n", [{"old_str": "   \n  \n", "new_str": "x"}], "d.txt"
            )
        self.assertIn("exact block not found", str(ctx.exception))
        self.assertNotIn("[Hint:", str(ctx.exception))

    def test_range_multiple_occurrences_raises(self):
        # count > 1 inside an explicit range without allow_multiple.
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(
                "d\nd\nd\n",
                [{"old_str": "d", "new_str": "D", "start_line": 1, "end_line": 3}],
                "d.txt",
            )
        self.assertIn("matches 3 occurrences in lines 1-3", str(ctx.exception))

    def test_range_allow_multiple_replaces_all(self):
        new, _ = apply_chunk_replacements(
            "d\nd\nd\n",
            [{"old_str": "d", "new_str": "D", "start_line": 1, "end_line": 3, "allow_multiple": True}],
            "d.txt",
        )
        self.assertEqual(new, "D\nD\nD\n")

    def test_range_target_not_found_anywhere(self):
        # full_count == 0 inside a range -> "target not found in <path> (s-e)"
        # without an occurrence-location message.
        with self.assertRaises(ValueError) as ctx:
            apply_chunk_replacements(
                "a\nb\nc\n", [{"old_str": "zzz", "new_str": "X", "start_line": 1, "end_line": 1}], "d.txt"
            )
        self.assertIn("target not found in 'd.txt' (1-1)", str(ctx.exception))

    def test_range_replacement_without_eol_appends_newline(self):
        # sub_text ends with \n and the target swallows it, leaving a replacement
        # without EOL -> EOL must be re-appended so lines are not joined.
        new, _ = apply_chunk_replacements(
            "a\nb\nc\n", [{"old_str": "a\nb\n", "new_str": "A", "start_line": 1, "end_line": 2}], "d.txt"
        )
        self.assertEqual(new, "A\nc\n")


# ---------------------------------------------------------------------------
# edit: tool-level file / path edge cases
# ---------------------------------------------------------------------------
class TestEditToolFiles(_Base):
    async def test_edit_nonexistent_returns_err(self):
        tool = EditTool()
        res = str(await tool.execute({"path": "missing.txt", "old_str": "a", "new_str": "b"}))
        self.assertIn("ERR:", res)
        self.assertIn("not found", res)

    async def test_edit_empty_old_str_returns_err(self):
        tool = EditTool()
        p = self.write("f.txt", "hello\n")
        res = str(await tool.execute({"path": p, "old_str": "", "new_str": "x"}))
        self.assertIn("ERR:", res)
        self.assertIn("cannot be empty", res)

    async def test_edit_missing_new_str_is_delete(self):
        tool = EditTool()
        p = self.write("f.txt", "line1\nTOK\nline3\n")
        res = str(await tool.execute({"path": p, "old_str": "TOK"}))
        self.assertIn("TOK", res)  # diff shows removal
        self.assertEqual(self.read("f.txt"), "line1\nline3\n")

    async def test_edit_binary_file_missing_err_prefix(self):
        # BUG: binary file triggers UnicodeDecodeError == ValueError, caught at
        # edit.py:314 `except ValueError as ve: return str(ve)` -> raw message
        # is returned WITHOUT the "ERR: " prefix, breaking error convention.
        tool = EditTool()
        full = os.path.join(self.tmp, "bin.bin")
        with open(full, "wb") as f:
            f.write(b"\xff\xfe\x80\x81\x00\x01")
        res = str(await tool.execute({"path": full, "old_str": "abc", "new_str": "def"}))
        self.assertIn("ERR:", res)  # RED: currently returns raw decode error w/o prefix

    async def test_edit_readonly_file_clobbers(self):
        # BUG: editing a write-protected (0444) file succeeds and clobbers it.
        # atomic_write_text (core/platform_utils.py:34 os.replace) replaces the
        # file inode regardless of file perms, silently writing a protected file.
        tool = EditTool()
        p = self.write("ro.txt", "keepme\nold\n")
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 0444 read-only
        try:
            res = str(await tool.execute({"path": p, "old_str": "old", "new_str": "new"}))
        finally:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
        # RED: current code reports success and rewrites the read-only file.
        self.assertIn("ERR:", res)

    async def test_edit_symlink_breaks_link_not_target(self):
        # BUG: when given an absolute symlink path, edit does NOT write the
        # symlink's target — resolve_path (tools/base.py:32) turns an absolute
        # path into a plain abspath (no realpath), then atomic_write_text's
        # os.replace replaces the symlink inode itself with a regular file,
        # destroying the symlink and leaving the target unchanged.
        tool = EditTool()
        target = self.write("real.txt", "hello world\n")
        link = os.path.join(self.tmp, "link.txt")
        os.symlink(target, link)
        res = str(await tool.execute({"path": link, "old_str": "world", "new_str": "there"}))
        self.assertNotIn("ERR:", res)
        # RED: target is left untouched (symlink replaced instead of followed).
        self.assertEqual(self.read("real.txt"), "hello there\n")

    async def test_edit_directory_returns_err(self):
        tool = EditTool()
        os.makedirs(os.path.join(self.tmp, "adir"), exist_ok=True)
        res = str(await tool.execute({"path": os.path.join(self.tmp, "adir"), "old_str": "a", "new_str": "b"}))
        self.assertIn("is a directory", res)

    async def test_edit_none_path_returns_err(self):
        tool = EditTool()
        res = str(await tool.execute({"path": None, "old_str": "a", "new_str": "b"}))
        self.assertIn("ERR:", res)

    async def test_edit_missing_path_returns_err(self):
        tool = EditTool()
        res = str(await tool.execute({"old_str": "a", "new_str": "b"}))
        self.assertIn("ERR:", res)

    async def test_edit_relative_path(self):
        tool = EditTool()
        self.write("rel.txt", "alpha\n")
        res = str(await tool.execute({"path": "rel.txt", "old_str": "alpha", "new_str": "beta"}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read("rel.txt"), "beta\n")

    async def test_edit_traversal_outside_works(self):
        # External files are allowed by design (see test_tools.py "External file outside workspace").
        tool = EditTool()
        outside = os.path.join(os.path.dirname(self.tmp), "outside_target.txt")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("outside\n")
        try:
            res = str(await tool.execute({"path": outside, "old_str": "outside", "new_str": "inside"}))
            self.assertNotIn("ERR:", res)
            with open(outside, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "inside\n")
        finally:
            if os.path.exists(outside):
                os.remove(outside)

    @pytest.mark.skipif(sys.platform == "win32", reason="quotes are invalid in Windows filenames")
    async def test_edit_unicode_cyrillic_path(self):
        tool = EditTool()
        p = self.write("файл пробел \"кавычки\".txt", "data\n")
        res = str(await tool.execute({"path": p, "old_str": "data", "new_str": "данные"}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read('файл пробел "кавычки".txt'), "данные\n")

    async def test_edit_start_end_line_keys(self):
        # schema uses start_line/end_line which the code reads directly
        tool = EditTool()
        p = self.write("s.txt", "a\nb\nb\nc\n")
        res = str(await tool.execute({"path": p, "old_str": "b", "new_str": "B", "start_line": 3, "end_line": 3}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read("s.txt"), "a\nb\nB\nc\n")

    async def test_edit_start_end_alias_keys_rejected(self):
        # start/end are no longer aliased to start_line/end_line.
        tool = EditTool()
        p = self.write("s2.txt", "a\nb\nb\nc\n")
        res = str(await tool.execute({"path": p, "old_str": "b", "new_str": "B", "start": 3, "end": 3}))
        self.assertIn("ERR:", res)

    async def test_edit_empty_file_target_not_found(self):
        tool = EditTool()
        p = self.write("empty.txt", "")
        res = str(await tool.execute({"path": p, "old_str": "x", "new_str": "y"}))
        self.assertIn("ERR:", res)

    async def test_edit_permutation_preserves_curly_straight(self):
        # old_str straight quotes, file has curly -> should preserve curly style
        tool = EditTool()
        p = self.write("q.txt", 'msg = "hello"\n')
        res = str(await tool.execute({"path": p, "old_str": 'msg = "hello"', "new_str": 'msg = "world"'}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read("q.txt"), 'msg = "world"\n')

    async def test_edit_allow_multiple_param(self):
        tool = EditTool()
        p = self.write("am.txt", "x\ndup\ndup\n")
        res = str(await tool.execute(
            {"path": p, "old_str": "dup", "new_str": "D", "allow_multiple": True}
        ))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read("am.txt"), "x\nD\nD\n")

    async def test_edit_delete_crlf_line_via_tool(self):
        tool = EditTool()
        p = self.write("crlf.txt", "line1\r\nTOK\r\nline3\r\n")
        res = str(await tool.execute({"path": p, "old_str": "TOK"}))
        self.assertNotIn("ERR:", res)
        with open(p, "r", encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), "line1\r\nline3\r\n")

    async def test_edit_empty_edits_like_range_target_not_found(self):
        # Range (1-1) with a target that exists nowhere else -> error names the
        # path AND the range, without a fake "elsewhere" line.
        tool = EditTool()
        p = self.write("rnf.txt", "a\nb\nc\n")
        res = str(await tool.execute({"path": p, "old_str": "zzz", "new_str": "X", "start_line": 1, "end_line": 1}))
        self.assertIn("ERR:", res)
        self.assertIn("target not found in", res)


# ---------------------------------------------------------------------------
# multi_edit: tool-level multi-chunk behavior
# ---------------------------------------------------------------------------
class TestMultiEditToolEdge(_Base):
    async def test_overlapping_chunks_error(self):
        tool = MultiEditTool()
        p = self.write("ov.txt", "line 1\nline 2\nline 3\nline 4\nline 5\n")
        res = str(await tool.execute(
            {
                "path": p,
                "edits": [
                    {"old_str": "line 2", "new_str": "line TWO", "start_line": 2, "end_line": 4},
                    {"old_str": "line 3", "new_str": "line THREE", "start_line": 3, "end_line": 5},
                ],
            }
        ))
        self.assertIn("ERR:", res)
        self.assertIn("overlap", res)
        # No partial application: file untouched.
        self.assertEqual(self.read("ov.txt"), "line 1\nline 2\nline 3\nline 4\nline 5\n")

    async def test_empty_edits_error(self):
        tool = MultiEditTool()
        p = self.write("e.txt", "abc\n")
        res = str(await tool.execute({"path": p, "edits": []}))
        self.assertIn("ERR:", res)
        self.assertIn("no replacement chunks", res)

    async def test_missing_edits_error(self):
        tool = MultiEditTool()
        p = self.write("e2.txt", "abc\n")
        res = str(await tool.execute({"path": p}))
        self.assertIn("ERR:", res)
        self.assertIn("no replacement chunks", res)

    async def test_chunk_error_is_atomic_no_partial_write(self):
        # Second chunk is malformed (missing old_str) -> nothing may be written.
        tool = MultiEditTool()
        p = self.write("atom.txt", "a = 1\nb = 2\nc = 3\n")
        res = str(await tool.execute(
            {
                "path": p,
                "edits": [
                    {"old_str": "a = 1", "new_str": "a = 10"},
                    {"new_str": "orphan"},
                ],
            }
        ))
        self.assertIn("ERR:", res)
        self.assertIn("chunk 2 missing 'old_str'", res)
        self.assertEqual(self.read("atom.txt"), "a = 1\nb = 2\nc = 3\n")

    async def test_chunks_sorted_desc_no_line_drift(self):
        # Chunk 1 (line 1) expands to two lines; chunk 2 targets line 3. Without
        # the descending sort the second range would drift into line 4.
        tool = MultiEditTool()
        p = self.write("drift.txt", "a\nb\nc\n")
        res = str(await tool.execute(
            {
                "path": p,
                "edits": [
                    {"old_str": "a", "new_str": "A1\nA2", "start_line": 1, "end_line": 1},
                    {"old_str": "c", "new_str": "C", "start_line": 3, "end_line": 3},
                ],
            }
        ))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read("drift.txt"), "A1\nA2\nb\nC\n")

    async def test_allow_multiple_in_one_chunk(self):
        tool = MultiEditTool()
        p = self.write("am2.txt", "dup\ndup\nkeep\n")
        res = str(await tool.execute(
            {
                "path": p,
                "edits": [
                    {"old_str": "dup", "new_str": "D", "allow_multiple": True},
                    {"old_str": "keep", "new_str": "K"},
                ],
            }
        ))
        self.assertNotIn("ERR:", res)
        self.assertEqual(self.read("am2.txt"), "D\nD\nK\n")

    async def test_none_chunk_returns_err(self):
        tool = MultiEditTool()
        p = self.write("nc.txt", "abc\n")
        res = str(await tool.execute({"path": p, "edits": [None]}))
        self.assertIn("ERR:", res)

    async def test_nonexistent_path_error(self):
        tool = MultiEditTool()
        res = str(await tool.execute(
            {"path": "missing.txt", "edits": [{"old_str": "a", "new_str": "b"}]}
        ))
        self.assertIn("ERR:", res)
        self.assertIn("not found", res)

    async def test_none_path_returns_err(self):
        tool = MultiEditTool()
        res = str(await tool.execute({"path": None, "edits": [{"old_str": "a", "new_str": "b"}]}))
        self.assertIn("ERR:", res)

    async def test_missing_target_fuzzy_hint(self):
        tool = MultiEditTool()
        p = self.write("fz.txt", "def calculate_total_price(items):\n    return sum(items)\n")
        res = str(await tool.execute(
            {
                "path": p,
                "edits": [{"old_str": "def calculate_total_price(item_list):", "new_str": "pass"}],
            }
        ))
        self.assertIn("ERR:", res)
        self.assertIn("Nearest matching code", res)


# ---------------------------------------------------------------------------
# create: path / content edge cases
# ---------------------------------------------------------------------------
class TestCreateTool(_Base):
    async def test_create_none_content_writes_empty(self):
        tool = CreateTool()
        p = os.path.join(self.tmp, "c.txt")
        res = str(await tool.execute({"path": p, "content": None}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(open(p, encoding="utf-8").read(), "")

    async def test_create_missing_content_writes_empty(self):
        tool = CreateTool()
        p = os.path.join(self.tmp, "c2.txt")
        res = str(await tool.execute({"path": p}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(open(p, encoding="utf-8").read(), "")

    async def test_create_path_none_returns_err(self):
        tool = CreateTool()
        res = str(await tool.execute({"path": None, "content": "x"}))
        self.assertIn("ERR:", res)

    async def test_create_binary_content_no_crash(self):
        # Fixed: bytes content no longer raises at create.py:48; decoded safely.
        tool = CreateTool()
        p = os.path.join(self.tmp, "c.bin")
        res = str(await tool.execute({"path": p, "content": b"\x00\x01binary"}))
        self.assertIn("created", res)

    async def test_create_parent_path_is_file_returns_err(self):
        tool = CreateTool()
        os.makedirs(os.path.join(self.tmp, "p"), exist_ok=True)
        with open(os.path.join(self.tmp, "p", "blocker"), "w", encoding="utf-8") as f:
            f.write("i am a file, not a dir")
        target = os.path.join(self.tmp, "p", "blocker", "child.txt")
        res = str(await tool.execute({"path": target, "content": "x"}))
        self.assertIn("ERR:", res)
        # The blocker file must NOT be clobbered.
        self.assertEqual(open(os.path.join(self.tmp, "p", "blocker"), encoding="utf-8").read(), "i am a file, not a dir")

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod read-only dir is ineffective on Windows")
    async def test_create_no_write_permission_returns_err(self):
        tool = CreateTool()
        ro_dir = os.path.join(self.tmp, "ro")
        os.makedirs(ro_dir, exist_ok=True)
        os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)  # read+exec only, no write
        try:
            target = os.path.join(ro_dir, "x.txt")
            res = str(await tool.execute({"path": target, "content": "x"}))
            self.assertIn("ERR:", res)
        finally:
            os.chmod(ro_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    async def test_create_unicode_cyrillic_path(self):
        tool = CreateTool()
        p = os.path.join(self.tmp, "папка", "файл — имя.txt")
        res = str(await tool.execute({"path": p, "content": "привет"}))
        self.assertNotIn("ERR:", res)
        self.assertTrue(os.path.exists(p))
        self.assertEqual(open(p, encoding="utf-8").read(), "привет")

    async def test_create_huge_content(self):
        tool = CreateTool()
        p = os.path.join(self.tmp, "big.txt")
        content = "x" * 200_000
        res = str(await tool.execute({"path": p, "content": content}))
        self.assertNotIn("ERR:", res)
        self.assertEqual(len(open(p, encoding="utf-8").read()), 200_000)

    async def test_create_trailing_newlines_stripped(self):
        tool = CreateTool()
        p = os.path.join(self.tmp, "nl.txt")
        await tool.execute({"path": p, "content": "a\n\n\n"})
        self.assertEqual(open(p, encoding="utf-8").read(), "a")

    async def test_create_overwrites_existing_file_and_returns_diff(self):
        tool = CreateTool()
        p = self.write("ov.txt", "original\n")
        res = str(await tool.execute({"path": p, "content": "replaced\n"}))
        self.assertNotIn("ERR:", res)
        self.assertIn("updated", res)
        # create strips trailing \r\n (tools/create.py:48), so no trailing newline preserved
        self.assertEqual(self.read("ov.txt"), "replaced")

    async def test_create_readonly_file_overwrite_bypasses_perm(self):
        # BUG: overwriting a read-only (0444) file succeeds via create.
        # atomic_write_text (core/platform_utils.py:34) os.replace new inode over
        # the old one, bypassing the target file's write permission — no error.
        tool = CreateTool()
        p = self.write("rov.txt", "old\n")
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        try:
            res = str(await tool.execute({"path": p, "content": "new\n"}))
            # RED: current code reports success and overwrites the read-only file.
            self.assertIn("ERR:", res)
        finally:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)

    async def test_create_ignores_alias_keys(self):
        # create reads only canonical 'path'/'content'; alias keys like
        # target_file/code are not mapped. Documenting strict behavior.
        tool = CreateTool()
        p = os.path.join(self.tmp, "alias.txt")
        res = str(await tool.execute({"target_file": p, "code": "hello"}))
        # Without alias normalization resolve_path(None) -> cwd dir.
        self.assertIn("ERR:", res)
        self.assertFalse(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()
