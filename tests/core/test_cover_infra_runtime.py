"""Coverage tests for infrastructure runtime & platform modules edge paths.

Covers core/infrastructure/platform/platform_utils.py,
core/infrastructure/runtime/fs_signature.py and
core/infrastructure/runtime/prompt_markdown.py. Self-contained: no external
commands are actually spawned (subprocess Popen is mocked), clipboard helpers
are exercised via injected mocks.
"""

import ctypes
import locale
import os
from unittest.mock import MagicMock, patch

import pytest

import core.infrastructure.platform.platform_utils as pu
import core.infrastructure.runtime.fs_signature as fs
from core.infrastructure.runtime.prompt_markdown import format_skills_markdown

# ---------------------------------------------------------------------------
# platform_utils.py
# ---------------------------------------------------------------------------


def test_fsync_path_open_failure(monkeypatch):
    def _boom(*a, **k):
        raise OSError("open fail")

    monkeypatch.setattr(pu.os, "open", _boom)
    pu._fsync_path_async("x")  # no raise


def test_fsync_path_submit_failure_closes_fd(monkeypatch):
    closed = []

    def fake_open(path, flags):
        return 42

    def fake_close(fd):
        closed.append(fd)
        raise OSError("close fail")  # close failure is swallowed too

    monkeypatch.setattr(pu.os, "open", fake_open)
    monkeypatch.setattr(pu.os, "close", fake_close)
    exec_mock = MagicMock()
    exec_mock.submit.side_effect = RuntimeError("submit fail")
    monkeypatch.setattr(pu, "_fsync_executor", lambda: exec_mock)
    pu._fsync_path_async("p")
    assert closed == [42]


def test_do_fsync_close_raises(monkeypatch):
    def fake_fsync(fd):
        return None

    def fake_close(fd):
        raise OSError("close fail")

    monkeypatch.setattr(pu.os, "fsync", fake_fsync)
    monkeypatch.setattr(pu.os, "close", fake_close)
    pu._do_fsync(9)  # no raise


def test_atomic_write_text_refuses_symlink(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    os.symlink(target, link)
    with pytest.raises(PermissionError):
        pu.atomic_write_text(str(link), "data")
    assert target.read_text() == "x"


def test_atomic_write_text_cleanup_on_failure(monkeypatch, tmp_path):
    dest = str(tmp_path / "out.txt")

    def _boom(*a, **k):
        raise RuntimeError("replace fail")

    monkeypatch.setattr(pu.os, "replace", _boom)
    with pytest.raises(RuntimeError):
        pu.atomic_write_text(dest, "data")
    # temp file cleaned up, target unclobbered
    assert not [p for p in os.listdir(tmp_path) if p.startswith(".johnston-")]


def test_atomic_write_text_cleanup_unlink_failure(monkeypatch, tmp_path):
    dest = str(tmp_path / "out2.txt")

    def _boom(*a, **k):
        raise RuntimeError("replace fail")

    def _unlink_boom(*a, **k):
        raise OSError("unlink fail")

    monkeypatch.setattr(pu.os, "replace", _boom)
    monkeypatch.setattr(pu.os, "unlink", _unlink_boom)
    with pytest.raises(RuntimeError):
        pu.atomic_write_text(dest, "data")


def test_decode_output_empty():
    assert pu.decode_output(b"") == ""


def test_decode_output_fallback_exhausted_uses_original(monkeypatch):
    # every fallback encoding raises LookupError -> original text is returned
    data = b"\xff\xfe" * 20
    monkeypatch.setattr(pu, "_output_fallback_encodings", lambda: ["__bad1__", "__bad2__"])
    res = pu.decode_output(data)
    assert isinstance(res, str)
    assert res


def test_output_fallback_encodings_mac_quietly_skips_windll(monkeypatch):
    # is_windows True but ctypes.windll access fails -> exception swallowed
    class NoWindll:
        @property
        def kernel32(self):
            raise OSError("no windll")

    monkeypatch.setattr(pu, "is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", NoWindll(), raising=False)
    encodings = pu._output_fallback_encodings()
    assert "utf-8" in encodings


def test_output_fallback_encodings_windows_oemcp(monkeypatch):
    class Wind:
        def __init__(self):
            self.kernel32 = MagicMock()
            self.kernel32.GetOEMCP.return_value = 437

    monkeypatch.setattr(pu, "is_windows", lambda: True)
    monkeypatch.setattr(ctypes, "windll", Wind(), raising=False)
    encodings = pu._output_fallback_encodings()
    assert "cp437" in encodings
    assert "utf-8" in encodings


def test_output_fallback_encodings_locale_raises(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("locale fail")

    monkeypatch.setattr(pu, "is_windows", lambda: False)
    monkeypatch.setattr(locale, "getpreferredencoding", _boom)
    encodings = pu._output_fallback_encodings()
    assert encodings == ["utf-8"]


def test_copy_to_os_clipboard_empty_text():
    pu.copy_to_os_clipboard("")  # early return


def test_copy_to_os_clipboard_windows_clip():
    with (
        patch("core.infrastructure.platform.platform_utils.is_windows", return_value=True),
        patch("core.infrastructure.platform.platform_utils.shutil.which"),
        patch("core.infrastructure.platform.platform_utils.subprocess.Popen") as popen,
    ):
        p = MagicMock()
        popen.return_value = p
        pu.copy_to_os_clipboard("hi")
    p.communicate.assert_called_once_with(input="hi")


def test_copy_to_os_clipboard_pbcopy():
    with (
        patch("core.infrastructure.platform.platform_utils.is_windows", return_value=False),
        patch("core.infrastructure.platform.platform_utils.shutil.which", side_effect=lambda n: n == "pbcopy"),
        patch("core.infrastructure.platform.platform_utils.subprocess.Popen") as popen,
    ):
        p = MagicMock()
        popen.return_value = p
        pu.copy_to_os_clipboard("hi")
    p.communicate.assert_called_once_with(input="hi")


def test_copy_to_os_clipboard_wl_copy():
    with (
        patch("core.infrastructure.platform.platform_utils.is_windows", return_value=False),
        patch("core.infrastructure.platform.platform_utils.shutil.which", side_effect=lambda n: n == "wl-copy"),
        patch("core.infrastructure.platform.platform_utils.subprocess.Popen") as popen,
    ):
        p = MagicMock()
        popen.return_value = p
        pu.copy_to_os_clipboard("hi")
    p.communicate.assert_called_once_with(input="hi")


def test_copy_to_os_clipboard_xclip():
    with (
        patch("core.infrastructure.platform.platform_utils.is_windows", return_value=False),
        patch(
            "core.infrastructure.platform.platform_utils.shutil.which",
            side_effect=lambda n: n == "xclip",
        ),
        patch("core.infrastructure.platform.platform_utils.subprocess.Popen") as popen,
    ):
        p = MagicMock()
        popen.return_value = p
        pu.copy_to_os_clipboard("hi")
    p.communicate.assert_called_once_with(input="hi")


def test_copy_to_os_clipboard_spawn_error_swallowed():
    with (
        patch("core.infrastructure.platform.platform_utils.is_windows", return_value=False),
        patch("core.infrastructure.platform.platform_utils.shutil.which", side_effect=lambda n: n == "pbcopy"),
        patch("core.infrastructure.platform.platform_utils.subprocess.Popen", side_effect=OSError("no pbcopy")),
    ):
        pu.copy_to_os_clipboard("hi")  # no raise


@pytest.mark.asyncio
async def test_copy_to_os_clipboard_async():
    with patch("core.infrastructure.platform.platform_utils.copy_to_os_clipboard") as m:
        await pu.copy_to_os_clipboard_async("hello")
    m.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# fs_signature.py
# ---------------------------------------------------------------------------


def _patch_scan(monkeypatch):
    """Deterministically control a directory scan (the source unpacks path
    strings, so scanning real dirs reaches the filesystem root)."""

    class Stats:
        st_mtime_ns = 1
        st_size = 2

    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(os.path, "isfile", lambda p: p.endswith(".txt"))
    monkeypatch.setattr(fs.os, "listdir", lambda p: ["a.txt", "sub"])
    monkeypatch.setattr(fs.os, "stat", lambda p: Stats())


def test_compute_dir_signature_skips_dirs_without_extensions(monkeypatch):
    _patch_scan(monkeypatch)
    sig = fs.compute_dir_signature(["fake/path"])
    assert sig is not None
    entry_paths = [e.path for e in sig]
    assert len(entry_paths) == 1
    assert entry_paths[0].endswith("a.txt")


def test_compute_dir_signature_listdir_raises(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(fs.os, "listdir", lambda p: (_ for _ in ()).throw(OSError("listdir fail")))
    assert fs.compute_dir_signature(["fake/path"]) is None


def test_compute_dir_signature_hash_accumulates(monkeypatch):
    _patch_scan(monkeypatch)
    h1 = fs.compute_dir_signature_hash(["fake/path"])
    h2 = fs.compute_dir_signature_hash(["fake/path"])
    assert isinstance(h1, int)
    assert h1 == h2


def test_compute_dir_signature_str_path_scans_real_dir(tmp_path):
    # Regression: compute_dir_signature used to unpack a str path per character
    # (``for dpath, *_ in dirs``), so the scan ran from the leading ``/`` of the
    # filesystem instead of the requested directory. A real str path must be
    # treated as a whole directory path.
    for name in ("a.txt", "b.md"):
        (tmp_path / name).write_text("x" if name == "a.txt" else "y")
    sig = fs.compute_dir_signature([str(tmp_path)], [".txt"])
    assert sig is not None
    paths = [e.path for e in sig]
    assert any(os.path.join(str(tmp_path), "a.txt") == p for p in paths)
    assert not any(os.path.join(str(tmp_path), "b.md") in p for p in paths)


def test_compute_dir_signature_tuple_item_picks_dir(tmp_path):
    # ``dirs`` may carry (dir, extra) tuple items; only the path component is
    # the directory actually scanned.
    (tmp_path / "c.txt").write_text("z")
    sig = fs.compute_dir_signature([(str(tmp_path), "extra")], [".txt"])
    assert sig is not None
    assert [e.path for e in sig] == [os.path.join(str(tmp_path), "c.txt")]


def test_recursive_stat_raises_skips_file(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(fs.os, "walk", lambda p: iter([("fake/root", [], ["f.txt"])]))
    monkeypatch.setattr(fs.os, "stat", lambda p: (_ for _ in ()).throw(OSError("stat fail")))
    assert fs.compute_dir_signature_recursive(["fake/path"]) == ()


def test_recursive_walk_raises_skips_dir(monkeypatch):
    monkeypatch.setattr(os.path, "isdir", lambda p: True)
    monkeypatch.setattr(fs.os, "walk", lambda p: (_ for _ in ()).throw(OSError("walk fail")))
    assert fs.compute_dir_signature_recursive(["fake/path"]) == ()


# ---------------------------------------------------------------------------
# prompt_markdown.py
# ---------------------------------------------------------------------------


def test_format_skills_markdown_full():
    class Scope:
        def __init__(self, value):
            self.value = value

    class Skill:
        def __init__(self, name, description, scope):
            self.name = name
            self.description = description
            self.scope = scope

    skills = [
        Skill("p1", "Proj desc", Scope("project")),
        Skill("g1", "", Scope("global")),
    ]
    md = format_skills_markdown(skills)
    assert "<skills>" in md
    assert '<skill name="p1" scope="project" desc="Proj desc"/>' in md
    assert '<skill name="g1" scope="global"/>' in md
    assert "</skills>" in md


if __name__ == "__main__":
    pytest.main([__file__])
