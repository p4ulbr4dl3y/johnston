"""Edge-case tests for core/frontmatter.py (parse_frontmatter, parse_csv_list, iter_md_files).

Failing tests document BUGS found in the implementation; they are kept red on purpose.
"""
import os

import pytest

from core.infrastructure.runtime.frontmatter import iter_md_files, parse_csv_list, parse_frontmatter

# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content", ["", "--", "---", "---\n", "not frontmatter"])
def test_no_closing_delimiter_returns_empty(content):
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert body == content


def test_content_starting_with_delimiter_no_closing():
    # "---\nkey: val" has only 2 parts after split("---",2) -> falls through to {}
    fm, body = parse_frontmatter("---\nkey: val")
    assert fm == {}
    assert body == "---\nkey: val"


def test_basic_key_value():
    fm, body = parse_frontmatter("---\nname: foo\n---\nBody text")
    assert fm == {"name": "foo"}
    assert body == "\nBody text"


def test_empty_value():
    fm, _ = parse_frontmatter("---\nkey:\n---")
    assert fm == {"key": ""}


def test_value_with_colons():
    fm, _ = parse_frontmatter("---\nkey: a:b:c\n---")
    assert fm == {"key": "a:b:c"}


def test_leading_space_key_not_parsed():
    fm, _ = parse_frontmatter("---\n  key: val\n---")
    assert "key" not in fm


def test_quoted_values_stripped():
    fm, _ = parse_frontmatter("---\na: 'va'\nb: \"vb\"\n---")
    assert fm == {"a": "va", "b": "vb"}


def test_inner_quote_preserved():
    fm, _ = parse_frontmatter("---\na: 'it'\n---")
    assert fm["a"] == "it"


def test_unicode_keys_values():
    fm, _ = parse_frontmatter("---\nключ: значение\nязык: русский\n---")
    assert fm == {"ключ": "значение", "язык": "русский"}


def test_multiline_continuation():
    fm, _ = parse_frontmatter("---\nkey: first\n  second\n  third\n---")
    assert fm["key"] == "first second third"


def test_multiline_block_folded():
    fm, _ = parse_frontmatter("---\nkey: >\n  line1\n  line2\n---")
    assert fm["key"] == "line1 line2"


def test_multiline_block_literal():
    fm, _ = parse_frontmatter("---\nkey: |\n  line1\n  line2\n---")
    assert fm["key"] == "line1 line2"


def test_lone_block_marker_empties_value():
    # BUG-ish: a value that is exactly ">" or "|" is silently wiped to ""
    fm, _ = parse_frontmatter("---\nkey: >\n---")
    assert fm == {"key": ""}


def test_crlf_line_endings():
    fm, body = parse_frontmatter("---\r\nkey: val\r\n---\r\nBody")
    assert fm == {"key": "val"}
    assert body == "\r\nBody"


def test_comment_lines_skipped():
    fm, _ = parse_frontmatter("---\n# comment\nkey: val\n---")
    assert fm == {"key": "val"}


def test_inline_comment_NOT_stripped():
    # BUG: inline comment after scalar value is kept in the value
    fm, _ = parse_frontmatter("---\nkey: val # comment\n---")
    assert fm["key"] == "val"


def test_multiple_empty_keys():
    fm, _ = parse_frontmatter("---\na:\nb:\nc: val\n---")
    assert fm == {"a": "", "b": "", "c": "val"}


def test_tab_indented_continuation():
    fm, _ = parse_frontmatter("---\nkey: a\n\tb\n---")
    assert fm["key"] == "a b"


def test_key_lowercased():
    fm, _ = parse_frontmatter("---\nNAME: foo\nRole: worker\n---")
    assert "name" in fm and "role" in fm


# ---------------------------------------------------------------------------
# parse_csv_list
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", [], [None, "", " "]])
def test_empty_inputs(raw):
    assert parse_csv_list(raw) == []


def test_non_string_scalars():
    assert parse_csv_list(5) == ["5"]
    assert parse_csv_list(1.5) == ["1.5"]


def test_comma_separated():
    assert parse_csv_list("a, b, c") == ["a", "b", "c"]


def test_bracketed():
    assert parse_csv_list("[a, b, c]") == ["a", "b", "c"]
    assert parse_csv_list("[a]") == ["a"]
    assert parse_csv_list("a]") == ["a"]


def test_whitespace_and_bare_commas():
    assert parse_csv_list("  ") == []
    assert parse_csv_list(",") == []
    assert parse_csv_list("a,,b") == ["a", "b"]


def test_comma_inside_quotes_not_supported():
    # BUG: naive split(",") breaks quoted values containing commas
    assert parse_csv_list('["a, b", c]') == ['"a', 'b"', "c"]


def test_unicode_list():
    assert parse_csv_list("[ключ, значение]") == ["ключ", "значение"]


def test_list_cleaned():
    assert parse_csv_list([" a ", "b", "", " "]) == ["a", "b"]


# ---------------------------------------------------------------------------
# iter_md_files
# ---------------------------------------------------------------------------

def _make_tree(tmp_path, files):
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")


def test_nonexistent_dir_skipped():
    assert list(iter_md_files([("/no/such/path", "s")])) == []


def test_empty_dirs_skipped():
    assert list(iter_md_files([])) == []
    assert list(iter_md_files([("", "s")])) == []


def test_yields_md_and_markdown(tmp_path):
    _make_tree(tmp_path, ["a.md", "b.markdown", "c.txt", "d" ])
    paths = {os.path.basename(p) for p, _ in iter_md_files([(str(tmp_path), "s")])}
    assert paths == {"a.md", "b.markdown"}


def test_uppercase_extension_NOT_matched(tmp_path):
    # BUG: ".MD"/".MARKDOWN" uppercase not matched (case-sensitive endswith)
    _make_tree(tmp_path, ["UPPER.MD", "UPPER.MARKDOWN"])
    assert list(iter_md_files([(str(tmp_path), "s")])) == []


def test_subdirectory_not_recursed(tmp_path):
    _make_tree(tmp_path, ["sub/nested.md"])
    assert list(iter_md_files([(str(tmp_path), "s")])) == []


def test_path_is_file_skipped(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    assert list(iter_md_files([(str(f), "s")])) == []


def test_sorted_by_name(tmp_path):
    _make_tree(tmp_path, ["b.md", "a.md", "c.md"])
    names = [os.path.basename(p) for p, _ in iter_md_files([(str(tmp_path), "s")])]
    assert names == ["a.md", "b.md", "c.md"]


def test_duplicate_dirs_deduped(tmp_path):
    _make_tree(tmp_path, ["a.md"])
    out = list(iter_md_files([(str(tmp_path), "s1"), (str(tmp_path), "s2")]))
    assert len(out) == 1


def test_source_inherited(tmp_path):
    _make_tree(tmp_path, ["a.md"])
    out = list(iter_md_files([(str(tmp_path), "global")]))
    assert out == [(str(tmp_path / "a.md"), "global")]
