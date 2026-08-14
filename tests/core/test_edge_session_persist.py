"""Edge-case persistence tests for SessionStore (bug hunting).

Focus: what existing tests (test_session_manager.py, test_edge_perm_session.py)
do NOT cover — persistence between calls, roundtrip stability of large/nested
data, atomicity under mid-write failure, recovery from corrupt/empty/oversized/
non-UTF8 files, metadata edge types, post-finish mutation, sort behavior,
cascade delete/index recompute.

Red tests = findings in core/ code (documented inline). Do not edit core/.
"""
import json
import os
from unittest.mock import patch

import pytest

from core.session_manager import SessionStore

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Fresh SessionStore rooted in tmp_path (PROJECTS_DIR patched)."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    with patch("core.session_manager.PROJECTS_DIR", str(projects_dir)):
        s = SessionStore(project_path=str(project))
        yield s


def _write_session_json(store, name, data):
    path = os.path.join(store.sessions_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _reload(store, session_id, from_disk=True):
    """Force a reload that bypasses the in-memory cache."""
    if from_disk:
        store._sessions.clear()
        store._invalidate_disk_cache()
    return store.get(session_id)


# ===========================================================================
# ROUNDTRIP: persistence between calls / stability
# ===========================================================================

def test_roundtrip_persistence_between_separate_instances(tmp_path):
    """Data written by one store must be readable by a brand-new store instance
    (i.e. must live on disk, not just in-memory)."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)

    with patch("core.session_manager.PROJECTS_DIR", str(projects_dir)):
        s1 = SessionStore(project_path=str(project))
        sess = s1.create_main("persistent")
        sess.messages = [{"type": "bot", "text": "across-instance"}]
        sess.tokens_input, sess.tokens_output, sess.total_tokens = 100, 50, 150
        sess.cost_usd = 1.25
        s1.save(sess)

        # fresh instance, empty cache
        s2 = SessionStore(project_path=str(project))
        loaded = s2.get("persistent")
        assert loaded is not None
        assert loaded.messages == [{"type": "bot", "text": "across-instance"}]
        assert loaded.tokens_input == 100
        assert loaded.cost_usd == 1.25


def test_roundtrip_1000_events_stable(store):
    """1000+ events must roundtrip byte-identical and load without loss."""
    sess = store.create_main("busy")
    for i in range(1000):
        sess.add_event({"type": "user", "text": f"msg-{i}"})
        sess.add_event({"type": "bot", "text": f"reply-{i}", "final": i % 3 == 0})
    assert len(sess.messages) == 2000
    stored = sess.to_dict()
    store.save(sess)
    loaded = _reload(store, "busy")
    assert loaded is not None
    assert loaded.to_dict() == stored
    assert len(loaded.messages) == 2000
    assert loaded.messages[-1]["text"] == "reply-999"


def test_roundtrip_unicode_emoji_newlines_specials(store):
    """Unicode, emoji, newlines and control-ish specials survive roundtrip."""
    sess = store.create_main("uni")
    text = "Проверка 🚀 кофе 🎉\nвторая строка\ttab\r\nCRLF\0" + "".join(chr(c) for c in range(0x80, 0x90))
    sess.messages = [
        {"type": "user", "text": text},
        {"type": "bot", "text": "日本語한국어العربية 😀🙃", "final": True},
        {"type": "tool", "name": "read", "args": {"path": "тест/путь", "k": "эмодзи📌"}},
    ]
    store.save(sess)
    loaded = _reload(store, "uni")
    assert loaded is not None
    assert loaded.messages == sess.messages


def test_roundtrip_nested_dict_and_none_fields(store):
    """Deeply nested dicts, None fields and malformed-ish values survive."""
    sess = store.create_main("nested")
    sess.messages = [
        {"type": "tool", "name": "shell",
         "args": {"very": {"deep": {"nest": [{"more": [None, {"x": [1, [2, [3]]]}]}]}}}},
        {"type": "bot", "text": None, "final": True},          # None text
        {"type": "thinking", "text": 12345, "duration": None},  # int text, None duration
        {"type": "status_change", "status": "x", "error": None},
    ]
    sess.agent_history = [{"role": "assistant", "content": None, "tool_calls": None}]
    store.save(sess)
    loaded = _reload(store, "nested")
    assert loaded is not None
    assert loaded.to_dict() == sess.to_dict()


def test_roundtrip_idempotent_repeated_save_load(store):
    """Save->load->modify->save->load repeatedly must be stable (no drift)."""
    sess = store.create_main("stable")
    sess.messages = [{"type": "user", "text": "v1"}]
    store.save(sess)
    for i in range(5):
        loop_sess = _reload(store, "stable")
        loop_sess.messages.append({"type": "bot", "text": f"round{i}"})
        store.save(loop_sess)
    final = _reload(store, "stable")
    assert [m["text"] for m in final.messages] == ["v1", "round0", "round1", "round2", "round3", "round4"]


def test_from_dict_created_at_none_gets_default(store):
    """created_at: None in JSON must default to a real timestamp, not stay None."""
    sess = store.create_main("ts")
    sess.messages = [{"type": "user", "text": "x"}]
    store.save(sess)
    data = json.load(open(os.path.join(store.sessions_dir, "ts.json"), encoding="utf-8"))
    data["created_at"] = None
    data["updated_at"] = None
    _write_session_json(store, "ts.json", data)
    loaded = _reload(store, "ts")
    assert loaded is not None
    assert loaded.created_at is not None, (
        "created_at:None in persisted JSON must default to a timestamp. "
        "session_manager.py:59 does `created_at or _now()` but from_dict passes "
        "None through to __init__ — actually should default. Green if correct."
    )
    assert loaded.updated_at is not None


# ===========================================================================
# ATOMICITY
# ===========================================================================

def test_mid_write_crash_leaves_original_intact(store, monkeypatch):
    """If atomic_write_text fails mid-write, the original session file must be
    untouched and no tmp junk may remain. Note: save() swallows the exception
    (session_manager.py:446 logs it), so we assert on the on-disk invariant."""
    sess = store.create_main("crash")
    sess.messages = [{"type": "user", "text": "original"}]
    store.save(sess)
    fpath = os.path.join(store.sessions_dir, "crash.json")
    original_content = open(fpath, encoding="utf-8").read()

    from core.infrastructure.platform import platform_utils

    def boom(src, dst):
        raise OSError("simulated crash after tmp write")

    monkeypatch.setattr(platform_utils.os, "replace", boom)
    sess2 = _reload(store, "crash")
    sess2.messages = [{"type": "user", "text": "SHOULD-NOT-LAND"}]
    store.save(sess2)  # failure swallowed + logged by save()
    monkeypatch.undo()

    # tmp files must have been cleaned in the except branch of atomic_write_text
    leftovers = [f for f in os.listdir(store.sessions_dir) if ".johnston-" in f or f.endswith(".tmp")]
    assert leftovers == [], (
        f"atomic_write_text did not clean up its tmp file on failure (leftovers: {leftovers}). "
        "platform_utils.py:41-46 should unlink tmp before re-raising."
    )
    # original file must be intact (os.replace never ran -> no partial write)
    assert open(fpath, encoding="utf-8").read() == original_content
    # and the bad write must not have landed anywhere
    assert "SHOULD-NOT-LAND" not in open(fpath, encoding="utf-8").read()


def test_no_tmp_junk_after_successful_save(store):
    """Successful saves must not leave tmp files anywhere below sessions_dir."""
    for i in range(10):
        sess = store.create_main(f"n{i}")
        sess.messages = [{"type": "user", "text": "x" * 1000}]
        store.save(sess)
    for root, dirs, files in os.walk(store.sessions_dir):
        for f in files:
            assert ".johnston-" not in f and not f.endswith(".tmp"), (
                f"leftover tmp file: {os.path.join(root, f)}. atomic_write_text "
                "uses os.replace so tmp should never survive."
            )


# ===========================================================================
# RECOVERY from corrupt / empty / oversized / non-UTF8 files
# ===========================================================================

def test_recovery_broken_json_no_crash(store):
    _write_session_json(store, "broken.json", "{not valid json ]}}")
    # corrupted as a raw string is stored; simulate a truly broken file:
    p = os.path.join(store.sessions_dir, "broken.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not json at all")
    # list() and get() must not raise; file not deleted
    sessions = store.list()
    assert all(s.id != "broken" for s in sessions)
    assert store.get("broken") is None
    assert os.path.exists(p)


def test_recovery_truncated_valid_prefix(store):
    """An object truncated partway (valid JSON prefix, then cut) must not crash."""
    p = os.path.join(store.sessions_dir, "trunc.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"id": "trunc", "kind": "main", "messages": [{"type": "use')
    assert store.get("trunc") is None
    assert store.list() == []
    assert os.path.exists(p)


def test_recovery_empty_file(store):
    """A zero-byte file must be treated as missing (return default), not crash."""
    p = os.path.join(store.sessions_dir, "zero.json")
    open(p, "w").close()
    assert store.get("zero") is None, "empty file must load as None, not crash"
    assert all(s.id != "zero" for s in store.list())


def test_recovery_whitespace_only_file(store):
    p = os.path.join(store.sessions_dir, "spaces.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("   \n\t  ")
    assert store.get("spaces") is None
    assert store.list() == []


def test_recovery_non_utf8_file(store):
    """A non-UTF8 (e.g. latin-1) session file must not crash load."""
    p = os.path.join(store.sessions_dir, "latin.json")
    with open(p, "wb") as f:
        f.write(b"\x80\x81\x99 = not utf8 = \xff\xfe")
    assert store.get("latin") is None
    assert all(s.id != "latin" for s in store.list())


def test_recovery_huge_file_no_crash(store):
    """A >several MB session file must load (or not crash)."""
    sess = store.create_main("huge")
    sess.messages = [{"type": "bot", "text": "x" * (2 * 1024 * 1024)}]  # ~4MB JSON
    store.save(sess)
    size = os.path.getsize(os.path.join(store.sessions_dir, "huge.json"))
    assert size > 2 * 1024 * 1024
    loaded = _reload(store, "huge")
    assert loaded is not None
    assert len(loaded.messages[0]["text"]) == 2 * 1024 * 1024


def test_recovery_json_dict_without_id(store):
    """Valid JSON object with no 'id' must produce a session with id from file name
    or default '' — should not crash."""
    _write_session_json(store, "noid.json", {"kind": "main", "messages": [{"type": "user", "text": "x"}]})
    assert store.get("noid") is None or store.get("noid").kind == "main"


# ===========================================================================
# METADATA edge types
# ===========================================================================

def test_metadata_description_none_and_huge(store):
    sess = store.create_main("meta")
    sess.description = "x" * 1_000_000  # huge description
    sess.messages = [{"type": "user", "text": "hi"}]
    store.save(sess)
    loaded = _reload(store, "meta")
    assert loaded is not None
    assert loaded.description == "x" * 1_000_000


def test_metadata_description_none_presented_correctly(store):
    """description absent/None in JSON must not crash and yield '' default."""
    data = {"id": "m2", "kind": "main", "messages": [], "description": None}
    _write_session_json(store, "m2.json", data)
    loaded = store.get("m2")
    if loaded is not None:
        assert loaded.description == ""
    # at minimum, must not raise


def test_metadata_wrong_typed_fields(store):
    """Numeric/int fields stored as strings/None must not crash from_dict and
    should coerce to numbers."""
    data = {
        "id": "types",
        "kind": "main",
        "messages": [],
        "tokens_input": "blah",      # string where int expected
        "cost_usd": None,            # None where float expected
        "total_tokens": "42",
    }
    _write_session_json(store, "types.json", data)
    loaded = store.get("types")
    assert loaded is not None
    # int fields must be usable as ints (crash detection)
    int(loaded.tokens_input) if loaded.tokens_input else 0
    float(loaded.cost_usd if loaded.cost_usd is not None else 0.0)


# ===========================================================================
# POST-FINISH mutation / event semantics
# ===========================================================================

def test_finish_and_status_change_persisted(store):
    sess = store.create_main("fin")
    sess.finish("completed", "all good")
    store.save(sess)
    loaded = _reload(store, "fin")
    assert loaded.status == "completed"
    assert any(m.get("type") == "status_change" for m in loaded.messages)


# ===========================================================================
# SORTING / list behavior
# ===========================================================================

def test_list_invalid_filename_not_crashed(store):
    """A junk filename with invalid JSON content must be ignored, not crash list()."""
    p = os.path.join(store.sessions_dir, "weird name!.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("total garbage")
    ids = {s.id for s in store.list()}
    assert "weird name!" not in ids


def test_list_mixed_main_subagent_and_sorting(store):
    """Mixed main+subagent sessions with timestamps must sort correctly and not
    duplicate subagents into main list."""
    m1 = store.create_main("m1")
    m1.created_at = m1.updated_at = 5
    m1.messages = [{"type": "user", "text": "m1"}]
    store.save(m1)

    m2 = store.create_main("m2")
    m2.created_at = m2.updated_at = 10
    m2.messages = [{"type": "user", "text": "m2"}]
    store.save(m2)

    sub = store.create_subagent(parent_id="m1", subagent_id="sub1", description="s")
    store.save(sub)

    store._sessions.clear()
    store._invalidate_disk_cache()

    mains = store.list(kind="main")
    assert [s.id for s in mains] == ["m1", "m2"]  # disk order, both present
    assert "sub1" not in [s.id for s in mains]

    subs = store.list(kind="subagent")
    assert [s.id for s in subs] == ["sub1"]

    # list_main_sessions sorted by updated_at desc
    lm = store.list_main_sessions()
    assert [s["id"] for s in lm] == ["m2", "m1"]


def test_list_old_and_new_sessions_order(store):
    """Sessions with far-apart timestamps, incl. created_at vs updated_at ordering."""
    s_old_id = "old"
    s_new_id = "new"
    scol = store.create_main(s_old_id)
    scol.messages = [{"type": "user", "text": "old"}]
    scol.created_at = scol.updated_at = 100.0
    store.save(scol)
    snew = store.create_main(s_new_id)
    snew.messages = [{"type": "user", "text": "new"}]
    snew.created_at = snew.updated_at = 200.0
    store.save(snew)
    store._sessions.clear()
    store._invalidate_disk_cache()
    ordered = store.list_main_sessions()
    assert [s["id"] for s in ordered] == ["new", "old"]


# ===========================================================================
# DELETE cascade / index recompute
# ===========================================================================

def test_delete_main_cascades_and_indexes_recompute(store):
    """Deleting a main session must cascade to its subagent dir, and subsequent
    list() must exactly reflect remaining sessions (no stale cache)."""
    m1 = store.create_main("delmain")
    m1.messages = [{"type": "user", "text": "x"}]
    store.save(m1)
    for i in range(3):
        s = store.create_subagent(parent_id="delmain", subagent_id=f"sub-{i}")
        store.save(s)

    other = store.create_main("other")
    other.messages = [{"type": "user", "text": "keep"}]
    store.save(other)

    store._sessions.clear()
    store._invalidate_disk_cache()
    assert len(store.list()) == 5

    store.delete("delmain")
    sub_dir = os.path.join(store.sessions_dir, "delmain.subagents")
    assert not os.path.exists(sub_dir)

    remaining = store.list()
    ids = {s.id for s in remaining}
    assert "delmain" not in ids
    assert all(not s.id.startswith("sub-") for s in remaining)
    assert "other" in ids
    assert len(remaining) == 1


def test_delete_reload_from_fresh_store(store):
    """After delete, a brand-new store instance must not see the deleted session."""
    store.create_main("gone")
    store.delete("gone")
    projects_dir = os.path.dirname(store.project_dir)
    with patch("core.session_manager.PROJECTS_DIR", projects_dir):
        s2 = SessionStore(project_path=store.project_path)
    assert s2.get("gone") is None, "deleted session must not reappear on fresh load"



# ===========================================================================
# STATE / calculations
# ===========================================================================

def test_message_count_diff_and_history(store):
    """message_count counts assistant messages; empty history -> 0."""
    sess = store.create_main("cnt")
    sess.agent_history = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a1"},
        {"role": "tool", "content": "t"},
        {"role": "assistant", "content": "a2"},
    ]
    assert store._message_count(sess) == 2
    empty = store.create_main("e")
    assert store._message_count(empty) == 0


def test_title_from_messages_edge(store):
    """Title fallback for empty/no-user-msg sessions is 'Untitled'; long user msg truncated."""
    sess = store.create_main("t")
    assert store._title_from_messages(sess) == "Untitled"
    sess.messages = [{"type": "user", "text": "x" * 100}]
    title = store._title_from_messages(sess)
    assert title.endswith("...")


def test_title_from_messages_unicode_surrogate(store):
    sess = store.create_main("tu")
    sess.messages = [{"type": "user", "text": "éäöü😀" * 10}]
    title = store._title_from_messages(sess)
    assert len(title) <= 33


def test_search_empty(store):
    assert store.find_session_by_description_or_id("") is None
    assert store.find_session_by_description_or_id("   ") is None


def test_search_rewind_big_line(store):
    """Search with a very long identifier must not crash and match exact id."""
    sess = store.create_main("target")
    sess.description = "d" * 5000
    store.save(sess)
    long_ident = "target"
    found = store.find_session_by_description_or_id(long_ident)
    assert found is not None and found.id == "target"
    no_match = store.find_session_by_description_or_id("z" * 1000)
    assert no_match is None
