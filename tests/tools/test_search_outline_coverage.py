"""Coverage-focused unit tests for ``johnston.core.tools.search.outline``.

Covers AST-argument formatting, pattern filtering of Python content, generic
regex symbols, cache invalidation, per-file outline processing and the
parallel/serial orchestration paths of ``_search_outline``.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

import johnston.core.tools.search.outline as outline_mod
from johnston.core.tools.search.outline import (
    GENERIC_GROUP_NAMES,
    RE_GENERIC_DEF,
    _format_ast_args,
    _outline_file,
    _outline_generic_content,
    _outline_generic_symbols,
    _outline_python_content,
    _OutlineCache,
    _search_outline,
)

PY_FILE = "sample.py"


@pytest.fixture(autouse=True)
def _clear_outline_cache():
    outline_mod._OUTLINE_CACHE.clear()
    yield
    outline_mod._OUTLINE_CACHE.clear()


def _make_tree(code: str) -> "object":
    import ast

    return ast.parse(code)


# --- _format_ast_args -----------------------------------------------------


def test_format_ast_args_posonly_vararg_kwonly_kwarg():
    tree = _make_tree("def f(a, /, b, *args, c, **kwargs): pass")
    fn = tree.body[0]
    assert _format_ast_args(fn.args) == "a, /, b, *args, c, **kwargs"


def test_format_ast_args_kwonly_without_vararg():
    tree = _make_tree("def f(a, *, b, c): pass")
    fn = tree.body[0]
    assert _format_ast_args(fn.args) == "a, *, b, c"


def test_format_ast_args_vararg_without_kwonly():
    tree = _make_tree("def f(a, *args): pass")
    fn = tree.body[0]
    assert _format_ast_args(fn.args) == "a, *args"


def test_format_ast_args_vararg_and_kwarg():
    tree = _make_tree("def f(*args, **kwargs): pass")
    fn = tree.body[0]
    assert _format_ast_args(fn.args) == "*args, **kwargs"


# --- _outline_python_content ----------------------------------------------


def test_outline_python_parse_error_returns_empty():
    assert _outline_python_content("def broken(:\n") == []


def test_outline_python_invalid_bases_are_omitted():
    symbols = _outline_python_content(
        "class C(call(), 3):\n    pass\n", file_rel_path=PY_FILE
    )
    assert len(symbols) == 1
    display, _, _ = symbols[0]
    assert display == "  1: class C:"


def test_outline_python_attribute_base():
    symbols = _outline_python_content(
        "class C(pkg.Base):\n    def helper(self): pass\n"
    )
    assert len(symbols) >= 2
    display, _, _ = symbols[0]
    assert display == "  1: class C(Base):"


def test_outline_python_name_base():
    symbols = _outline_python_content(
        "class C(Plain):\n    def helper(self): pass\n"
    )
    assert len(symbols) >= 2
    display, _, _ = symbols[0]
    assert display == "  1: class C(Plain):"


def test_outline_python_async_method():
    symbols = _outline_python_content(
        "class C:\n    async def fetch(self):\n        return 1\n"
    )
    assert len(symbols) == 2
    display, lineno, name = symbols[1]
    assert display == "    2: async def fetch(self)"
    assert (lineno, name) == (2, "fetch")


def test_outline_python_method_pattern_query():
    symbols = _outline_python_content(
        "class C:\n    def run(self): pass\n    def stop(self): pass\n",
        pattern="run",
    )
    displays = [s[0] for s in symbols]
    assert len(displays) == 2
    assert displays[0].startswith("  1: class C:")
    assert "run" in displays[1]
    assert "stop" not in displays[1]


def test_outline_python_class_only_query():
    symbols = _outline_python_content(
        "class Alpha:\n    def run(self): pass\nclass Beta:\n    def run(self): pass\n",
        pattern="alpha",
    )
    displays = [s[0] for s in symbols]
    assert len(displays) == 2  # class line + its run method
    assert "Alpha" in displays[0]
    assert "Beta" not in "".join(displays)


def test_outline_python_class_and_function_queries():
    code = "class Runner:\n    def go(self): pass\n"
    assert len(_outline_python_content(code, pattern="runner")) == 2
    assert len(_outline_python_content(code, pattern="go")) == 2
    assert len(_outline_python_content(code, pattern="nope")) == 0
    assert len(_outline_python_content(code, pattern="*")) == 2
    assert len(_outline_python_content(code, pattern="  ")) == 2
    assert len(_outline_python_content(code)) == 2


def test_outline_python_top_level_async_function():
    symbols = _outline_python_content("async def poll():\n    return 0\n")
    assert len(symbols) == 1
    display, lineno, name = symbols[0]
    assert display == "  1: async def poll()"
    assert (lineno, name) == (1, "poll")


# --- _outline_generic_symbols ---------------------------------------------


def test_outline_generic_symbols_js_go():
    code = "const handler = (e) => e;\nfunction named() {}\n"
    symbols = _outline_generic_symbols(code)
    assert any(name == "handler" for _, _, name in symbols)
    assert any(name == "named" for _, _, name in symbols)


def test_outline_generic_symbols_ruby_haskell():
    code = "module M\ndef greet!\nend\n\ndata Person = Person String\n"
    symbols = _outline_generic_symbols(code)
    names = {name for _, _, name in symbols}
    assert names == {"M", "greet", "Person"}


def test_outline_generic_symbols_php_dart_elixir():
    code = (
        "class Order {}\n"
        "trait Discountable {}\n"
        "mixin Logging {}\n"
        "defmodule Shop do\n"
        "end\n"
    )
    names = {name for _, _, name in _outline_generic_symbols(code)}
    assert {"Order", "Discountable", "Logging", "Shop"} <= names


def test_outline_generic_symbols_long_display_truncated():
    long_name = "f" * 200
    code = f"function {long_name}() {{}}\n"
    symbols = _outline_generic_symbols(code)
    assert len(symbols) == 1
    display, lineno, name = symbols[0]
    assert len(display) == 125  # '  1: ' (5) + 117 + '...' (3)
    assert display.endswith("...")
    assert name == long_name
    assert lineno == 1


def test_outline_generic_symbols_single_line_number():
    symbols = _outline_generic_symbols("function first() {}\n\nfunction_second() {}\n")
    assert len(symbols) == 1
    assert symbols[0][1] == 1


def test_outline_generic_symbols_no_groups_skipped(monkeypatch):
    def _no_groups(match):
        return None

    monkeypatch.setattr(
        outline_mod, "GENERIC_GROUP_NAMES", tuple(["_nonexistent_group"])
    )
    assert _outline_generic_symbols("function anything() {}\n") == []


def test_outline_generic_symbols_broken_group_access(monkeypatch):
    def _broken_group(match):
        raise re.error("bad group")  # noqa: F821

    monkeypatch.setattr(
        outline_mod, "GENERIC_GROUP_NAMES", tuple(["missing_group", "fn"])
    )
    symbols = _outline_generic_symbols("function broken_group() {}\n")
    assert len(symbols) == 1
    assert symbols[0][2] == "broken_group"


def test_outline_generic_content_filters_by_pattern_and_globals():
    code = "function alpha() {}\nfunction beta() {}\n"
    assert len(_outline_generic_content(code)) == 2
    assert len(_outline_generic_content(code, pattern="alpha")) == 1
    assert len(_outline_generic_content(code, pattern="BETA")) == 1
    assert len(_outline_generic_content(code, pattern="*")) == 2
    assert len(_outline_generic_content(code, pattern="   ")) == 2
    assert GENERIC_GROUP_NAMES
    assert RE_GENERIC_DEF.search("struct Point { int x; };") is not None


# --- _OutlineCache --------------------------------------------------------


def test_outline_cache_mtime_mismatch_evicts():
    cache = _OutlineCache(max_size=4)
    key = "/tmp/main.py"
    cache.put(key, 10.0, [(" 1: def a()", 1, "a")])
    cache.put(key, 11.0, [(" 1: def b()", 1, "b")])
    assert cache._cache == {key: (11.0, [(" 1: def b()", 1, "b")])}
    assert cache.get(key, 11.0) == [(" 1: def b()", 1, "b")]
    assert cache._cache == {key: (11.0, [(" 1: def b()", 1, "b")])}


def test_outline_cache_mtime_del_keyerror_suppressed():
    cache = _OutlineCache(max_size=4)
    key = "/tmp/main.py"
    cache.put(key, 10.0, [(" 1: def a()", 1, "a")])
    with patch.object(cache._lru, "__delitem__", side_effect=KeyError(key)):
        assert cache.get(key, 99.0) is None


def test_outline_cache_miss_and_clear():
    cache = _OutlineCache(max_size=4)
    assert cache.get("/tmp/nope.py", 0.0) is None
    cache.put("/tmp/a.py", 1.0, [(" 1: def a()", 1, "a")])
    cache.clear()
    assert cache.get("/tmp/a.py", 1.0) is None


# --- _outline_file --------------------------------------------------------


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return str(p)


def test_outline_file_oversized_returns_none(tmp_path):
    p = tmp_path / "big.py"
    p.write_text("def x(): pass\n")
    with patch("os.path.getsize", return_value=outline_mod.MAX_OUTLINE_FILE_BYTES + 1):
        assert _outline_file(str(p), str(tmp_path), "*", None) is None


def test_outline_file_getsize_error_returns_none(tmp_path):
    p = tmp_path / "ghost.py"
    with patch("os.path.getsize", side_effect=OSError("gone")):
        assert _outline_file(str(p), str(tmp_path), "*", None) is None


def test_outline_file_glob_and_extension_filters(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    assert _outline_file(p, str(tmp_path), "*", "*.js") is None
    assert _outline_file(p, str(tmp_path), "*", "*.py") is not None
    txt = _write(tmp_path, "notes.txt", "class NotCode:\n    pass\n")
    assert _outline_file(txt, str(tmp_path), "*", None) is None


def test_outline_file_binary_skipped(tmp_path):
    p = tmp_path / "compiled.py"
    p.write_bytes(b"def f():\n    pass\n\x00\xff binary")
    assert _outline_file(str(p), str(tmp_path), "*", None) is None


def test_outline_file_open_error_returns_none(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    with patch("builtins.open", side_effect=OSError("denied")):
        assert _outline_file(p, str(tmp_path), "*", None) is None


def test_outline_file_cache_put_error_suppressed(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    with patch.object(
        outline_mod._OUTLINE_CACHE, "put", side_effect=RuntimeError("full")
    ):
        res = _outline_file(p, str(tmp_path), "*", None)
    assert res is not None


def test_outline_file_mtime_error_and_use_cache_false(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    with patch("os.path.getmtime", side_effect=OSError("gone")):
        res = _outline_file(p, str(tmp_path), "*", None, use_cache=True)
    assert res is not None
    assert any("alpha" in line for line in res[1])
    # Fresh extraction on every call without cache
    res2 = _outline_file(p, str(tmp_path), "*", None, use_cache=False)
    assert res2 is not None


def test_outline_file_name_only_filter(tmp_path):
    p = _write(tmp_path, "sample.py", "class Alpha:\n    def beta(self): pass\n")
    res = _outline_file(p, str(tmp_path), "beta", None)
    assert res is not None
    assert any("beta" in line for line in res[1])
    assert not any("Alpha" in line for line in res[1])


def test_outline_file_case_sensitive_filter(tmp_path):
    p = _write(tmp_path, "sample.py", "def AlphaBeta(): pass\ndef alphabeta(): pass\n")
    lower = _outline_file(p, str(tmp_path), "alphabeta", None, case_sensitive=False)
    assert lower is not None
    assert len(lower[1]) == 2
    upper = _outline_file(p, str(tmp_path), "alphabeta", None, case_sensitive=True)
    assert upper is not None
    assert any("alphabeta" in line for line in upper[1])
    assert not any("AlphaBeta" in line for line in upper[1])


def test_outline_file_no_filtered_results_returns_none(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    assert _outline_file(p, str(tmp_path), "missing_symbol", None) is None


def test_outline_file_generic_fallback(tmp_path):
    p = _write(tmp_path, "mod.ts", "const helper = (x) => x;\n")
    res = _outline_file(p, str(tmp_path), "helper", None)
    assert res is not None
    assert any("helper" in line for line in res[1])


def test_outline_file_python_ast_fallback_via_unavailable_ts(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha():\n    pass\n")
    with patch.object(
        outline_mod.GLOBAL_TREE_SITTER, "is_available", return_value=False
    ):
        res = _outline_file(p, str(tmp_path), "alpha", None)
    assert res is not None
    assert any("alpha" in line for line in res[1])


def test_outline_file_uses_tree_sitter(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha():\n    pass\n")
    fake_symbols = [(" 1: def alpha()", 1, "alpha")]
    fake_ts = MagicMock()
    fake_ts.is_available.return_value = True
    fake_ts.extract_symbols.return_value = fake_symbols
    with patch.object(outline_mod, "GLOBAL_TREE_SITTER", fake_ts):
        res = _outline_file(p, str(tmp_path), "*", None)
    assert res is not None
    assert res[1] == [fake_symbols[0][0]]


def test_outline_file_cache_hit_avoids_reparse(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    first = _outline_file(p, str(tmp_path), "*", None)
    assert first is not None
    orig = outline_mod._outline_python_content
    calls = []
    with patch.object(
        outline_mod,
        "_outline_python_content",
        side_effect=lambda *a, **k: calls.append(1) or orig(*a, **k),
    ):
        second = _outline_file(p, str(tmp_path), "*", None)
    assert second is not None
    assert calls == []


# --- _search_outline orchestration ---------------------------------------


def test_search_outline_cancel_precheck(tmp_path):
    event = threading.Event()
    event.set()
    assert _search_outline(str(tmp_path), "*", str(tmp_path), cancel_event=event) == (
        [],
        0,
        0,
    )


def test_search_outline_file_target(tmp_path):
    p = _write(tmp_path, "sample.py", "def alpha(): pass\n")
    lines, total, files = _search_outline(p, "*", str(tmp_path))
    assert total == 1
    assert files == 1
    assert lines[0].startswith("sample.py:")
    assert "alpha" in lines[1]


def test_search_outline_missing_target(tmp_path):
    assert _search_outline(str(tmp_path / "nope"), "*", str(tmp_path)) == ([], 0, 0)


def test_search_outline_dirs_with_and_without_globs(tmp_path):
    (tmp_path / "sub").mkdir()
    _write(tmp_path, "sample.py", "def alpha(): pass\n")
    _write(tmp_path, "notes.txt", "plain text\n")
    lines, total, files = _search_outline(str(tmp_path), "*", str(tmp_path))
    assert files == 1
    assert any("sample.py" in line for line in lines)
    lines_glob, total_glob, _ = _search_outline(
        str(tmp_path), "*", str(tmp_path), glob_pattern="*.py"
    )
    assert total_glob == 1
    assert lines_glob


def test_search_outline_max_results_serial(tmp_path):
    (tmp_path / "a.py").write_text("def alpha(): pass\ndef beta(): pass\n")
    lines, total, files = _search_outline(str(tmp_path), "*", str(tmp_path), max_results=1)
    assert total == 1
    assert files == 1
    assert not any("beta" in line for line in lines)


def test_search_outline_parallel_many_files(tmp_path):
    for i in range(30):
        (tmp_path / f"file_{i:02d}.py").write_text(f"def func{i}(): pass\n")
    lines, total, files = _search_outline(
        str(tmp_path), "func5", str(tmp_path), max_results=100
    )
    assert files > 0
    assert total >= 1
    assert any("func5" in line for line in lines)


def test_search_outline_parallel_cancel_event(tmp_path):
    for i in range(30):
        (tmp_path / f"file_{i:02d}.py").write_text(f"def func{i}(): pass\n")
    event = threading.Event()
    event.set()
    lines, total, files = _search_outline(
        str(tmp_path), "*", str(tmp_path), max_results=100, cancel_event=event
    )
    assert (lines, total, files) == ([], 0, 0)


def test_search_outline_parallel_cancel_within_futures(tmp_path):
    for i in range(30):
        (tmp_path / f"file_{i:02d}.py").write_text(f"def func{i}(): pass\n")
    event = threading.Event()

    def _set_and_raise(*args, **kwargs):
        event.set()
        raise RuntimeError("boom")

    with patch.object(outline_mod, "_outline_file", side_effect=_set_and_raise):
        lines, total, files = _search_outline(
            str(tmp_path), "*", str(tmp_path), max_results=100, cancel_event=event
        )
    assert (lines, total, files) == ([], 0, 0)


def test_search_outline_parallel_future_exception_skipped(tmp_path):
    for i in range(25):
        (tmp_path / f"file_{i:02d}.py").write_text(f"def func{i}(): pass\n")

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    with patch.object(outline_mod, "_outline_file", side_effect=_boom):
        lines, total, files = _search_outline(
            str(tmp_path), "*", str(tmp_path), max_results=100
        )
    assert (lines, total, files) == ([], 0, 0)


def test_search_outline_parallel_progress_and_max_results_break(tmp_path):
    for i in range(30):
        (tmp_path / f"file_{i:02d}.py").write_text(f"def func{i}(): pass\n")
    events = []

    def cb(event):
        events.append(event)

    lines, total, files = _search_outline(
        str(tmp_path), "*", str(tmp_path), max_results=2, progress_callback=cb
    )
    assert total == 2
    stages = {e.get("stage") for e in events}
    assert "outline_parallel" in stages
    assert "outline_complete" in stages
    assert "outline_progress" in stages


def test_search_outline_serial_cancel_break_and_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("skip.py\n")
    _write(tmp_path, "sample.py", "def alpha(): pass\n")
    _write(tmp_path, "skip.py", "def hidden(): pass\n")
    matcher = outline_mod._GitignoreMatcher.load_from_root(str(tmp_path))
    assert matcher is not None
    lines, total, files = _search_outline(
        str(tmp_path), "*", str(tmp_path), gitignore_matcher=matcher
    )
    assert files == 1
    assert any("alpha" in line for line in lines)
    assert not any("hidden" in line for line in lines)

    event = threading.Event()
    event.set()
    assert _search_outline(
        str(tmp_path), "*", str(tmp_path), gitignore_matcher=matcher, cancel_event=event
    ) == ([], 0, 0)


def test_search_outline_serial_cancel_mid_loop(tmp_path):
    """Cancel set after the pre-check breaks the serial loop (line 450)."""
    _write(tmp_path, "sample.py", "def alpha(): pass\n")
    _write(tmp_path, "other.py", "def beta(): pass\n")
    event = threading.Event()
    orig = outline_mod._outline_file

    def _set_on_first_call(*args, **kwargs):
        event.set()
        return orig(*args, **kwargs)

    with patch.object(outline_mod, "_outline_file", side_effect=_set_on_first_call):
        lines, total, files = _search_outline(
            str(tmp_path), "*", str(tmp_path), cancel_event=event
        )
    assert (lines, total, files) == ([], 0, 0)
