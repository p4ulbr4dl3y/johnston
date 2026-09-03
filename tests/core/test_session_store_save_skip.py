"""Focused tests for SessionStore no-op save skipping (perf fix M3).

Saves are debounced (~1.5s + per-turn coalescing), so the same session is
frequently re-saved with no persistent change; each such save used to
re-serialize the whole session and atomically rewrite the whole JSONL file
(O(session size) per save). ``SessionStore.save`` now skips the write when
nothing changed, and writes exactly the bytes a reader would otherwise see.
"""
import json
import os
from unittest.mock import patch

import pytest

from core.domain.entities.session import AgentSession
from core.infrastructure.storage import session_store as session_store_mod
from core.infrastructure.storage.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    """Fresh SessionStore rooted in tmp_path (PROJECTS_DIR patched)."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    with patch("core.infrastructure.storage.session_store.PROJECTS_DIR", str(projects_dir)):
        s = SessionStore(project_path=str(project))
        yield s


@pytest.fixture
def write_spy(monkeypatch):
    """Count atomic_write_text calls (the whole-file rewrite)."""
    calls = []
    real = session_store_mod.atomic_write_text

    def spy(path, data):
        calls.append(path)
        real(path, data)

    monkeypatch.setattr(session_store_mod, "atomic_write_text", spy)
    return calls


def _path(store, name):
    return os.path.join(store.sessions_dir, name)


def _read(store, name):
    with open(_path(store, name), encoding="utf-8") as f:
        return f.read()


def _reload_from_disk(store, session_id):
    store._sessions.clear()
    store._invalidate_disk_cache()
    return store.get(session_id)


# ---------------------------------------------------------------------------
# (a) second save with no mutation performs no write
# ---------------------------------------------------------------------------

def test_second_save_no_mutation_skips_write(store, write_spy):
    sess = store.create_main("s1")
    sess.messages = [{"type": "user", "text": "hi"}, {"type": "bot", "text": "yo"}]
    sess.tokens_input = 10
    store.save(sess)
    fpath = _path(store, "s1.jsonl")
    before = (os.path.getmtime(fpath), os.path.getsize(fpath), _read(store, "s1.jsonl"))
    write_spy.clear()

    store.save(sess)  # no mutation since last save

    after = (os.path.getmtime(fpath), os.path.getsize(fpath), _read(store, "s1.jsonl"))
    assert write_spy == []
    assert after == before, "no-op save must not rewrite the file"


def test_resave_identical_session_object_skips_write(store, write_spy):
    """A freshly loaded session with identical content must also be skipped."""
    sess = store.create_main("s2")
    sess.messages = [{"type": "user", "text": "q"}]
    store.save(sess)
    loaded = AgentSession.from_file(_path(store, "s2.jsonl"))
    assert loaded is not None
    write_spy.clear()

    store.save(loaded)

    assert write_spy == []
    assert _reload_from_disk(store, "s2").messages == [{"type": "user", "text": "q"}]


def test_second_save_after_touch_writes(store, write_spy):
    """Scalar change (touch -> updated_at) must still trigger a write."""
    sess = store.create_main("s3")
    sess.messages = [{"type": "user", "text": "q"}]
    store.save(sess)
    sess.touch()
    write_spy.clear()

    store.save(sess)

    assert len(write_spy) == 1
    loaded = _reload_from_disk(store, "s3")
    assert loaded.messages == [{"type": "user", "text": "q"}]
    assert loaded.updated_at == sess.updated_at


def test_first_save_always_writes_empty_store(store, write_spy):
    """A store with no prior state for the file must always initialize it."""
    sess = store.create_main("fresh")
    sess.messages = [{"type": "user", "text": "q"}]
    store.save(sess)
    assert len(write_spy) == 1
    assert _reload_from_disk(store, "fresh").messages == [{"type": "user", "text": "q"}]


# ---------------------------------------------------------------------------
# (b) save after appending one message grows the file by exactly one line
# ---------------------------------------------------------------------------

def test_append_one_message_grows_file_by_one_line(store):
    sess = store.create_main("grow")
    sess.messages = [{"type": "user", "text": "q1"}, {"type": "bot", "text": "a1"}]
    store.save(sess)
    lines_before = len(_read(store, "grow.jsonl").splitlines())

    sess.add_event({"type": "user", "text": "q2"})
    store.save(sess)

    lines_after = len(_read(store, "grow.jsonl").splitlines())
    assert lines_after == lines_before + 1, "one new message == one new line"
    assert '"q2"' in _read(store, "grow.jsonl")
    loaded = _reload_from_disk(store, "grow")
    assert loaded.messages[-1]["text"] == "q2"


# ---------------------------------------------------------------------------
# (c) from_file round-trip after sequential saves matches in-memory session
# ---------------------------------------------------------------------------

def test_roundtrip_after_multiple_saves_matches_memory(store, write_spy):
    sess = store.create_main("multi")
    sess.title = "T0"
    sess.messages = [{"type": "user", "text": "q1"}]
    store.save(sess)
    write_spy.clear()

    sess.add_event({"type": "bot", "text": "a1", "final": True})
    sess.add_event({"type": "tool", "tool_type": "shell", "target": "x", "args": {"cmd": "ls"}})
    sess.tokens_input, sess.tokens_output, sess.total_tokens = 10, 5, 15
    store.save(sess)

    sess.add_event({"type": "tool", "result_text": "ok", "status": "done"})
    sess.add_event({"type": "bot", "text": "a2", "final": True})
    sess.title = "Renamed"
    sess.status = "completed"
    sess.cost_usd = 0.42
    store.save(sess)

    # 2 real changes + an extra no-op save must cost exactly 2 rewrites.
    store.save(sess)
    assert len(write_spy) == 2

    loaded = _reload_from_disk(store, "multi")
    assert loaded.messages == sess.messages
    assert loaded.agent_history == sess.agent_history
    assert loaded.title == "Renamed"
    assert loaded.status == "completed"
    assert loaded.tokens_input == 10
    assert loaded.tokens_output == 5
    assert loaded.total_tokens == 15
    assert loaded.cost_usd == 0.42


# ---------------------------------------------------------------------------
# (d) restart simulation: a new store instance reads the grown file
# ---------------------------------------------------------------------------

def test_restart_new_store_reads_multiple_saves(tmp_path):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)

    with patch("core.infrastructure.storage.session_store.PROJECTS_DIR", str(projects_dir)):
        s1 = SessionStore(project_path=str(project))
        sess = s1.create_main("restart")
        sess.messages = [{"type": "user", "text": "q1"}]
        s1.save(sess)
        sess.add_event({"type": "bot", "text": "a1"})
        sess.tokens_input, sess.tokens_output = 3, 4
        s1.save(sess)
        s1.save(sess)  # no-op in the first process

        # "restart": brand-new store, empty caches.
        s2 = SessionStore(project_path=str(project))
        loaded = s2.get("restart")
        assert loaded is not None
        assert [m["text"] for m in loaded.messages] == ["q1", "a1"]
        assert loaded.tokens_input == 3
        assert loaded.tokens_output == 4

        # The restarted store can keep saving (first write after restart is
        # a full write, then skips apply again) and a third store reads back.
        loaded.add_event({"type": "user", "text": "q2"})
        s2.save(loaded)
        s2.save(loaded)  # no-op

        s3 = SessionStore(project_path=str(project))
        reloaded = s3.get("restart")
        assert [m["text"] for m in reloaded.messages] == ["q1", "a1", "q2"]


# ---------------------------------------------------------------------------
# (e) truncation / rewind paths still correct (full rewrite, no stale lines)
# ---------------------------------------------------------------------------

def test_truncate_messages_rewrites_correctly(store, write_spy):
    sess = store.create_main("rewind")
    sess.messages = [
        {"type": "user", "text": "q1"},
        {"type": "bot", "text": "a1"},
        {"type": "user", "text": "q2"},
        {"type": "bot", "text": "a2"},
    ]
    sess.agent_history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    store.save(sess)
    write_spy.clear()

    # Simulate rewind: replace transcript with a shorter prefix (new list).
    sess.messages = [m for m in sess.messages[:1]]
    sess.agent_history = []
    sess.tokens_input = 0
    store.save(sess)
    store.save(sess)  # no-op after truncation

    assert len(write_spy) == 1  # initial + truncation, no-op skipped
    loaded = _reload_from_disk(store, "rewind")
    assert [m["text"] for m in loaded.messages] == ["q1"]
    assert loaded.agent_history == []
    assert loaded.tokens_input == 0


# ---------------------------------------------------------------------------
# In-place mutation of an EARLIER message (widget tool-result merge) persists
# ---------------------------------------------------------------------------

def test_inplace_early_message_mutation_still_saved(store, write_spy):
    """message_flow mutates msg['result_text']/msg['status'] on a non-last
    message with no length/meta change — the content check must catch it."""
    sess = store.create_main("toolmerge")
    sess.messages = [
        {"type": "user", "text": "run"},
        {"type": "tool", "tool_type": "shell", "target": "x", "args": {}},
        {"type": "bot", "text": "done"},
    ]
    store.save(sess)
    write_spy.clear()

    sess.messages[1]["result_text"] = "finished ok"
    sess.messages[1]["status"] = "done"
    store.save(sess)

    assert len(write_spy) == 1
    loaded = _reload_from_disk(store, "toolmerge")
    assert loaded.messages[1]["result_text"] == "finished ok"
    assert loaded.messages[1]["status"] == "done"
    assert loaded.messages == sess.messages


def test_live_agent_history_appends_persisted(store, write_spy):
    """Subagent streams persist the live agent.history (via _history())."""
    sess = store.create_main("livehist")
    sess.messages = [{"type": "user", "text": "q"}]

    class FakeAgent:
        history = [{"role": "user", "content": "q"}]

    sess.agent = FakeAgent
    store.save(sess)
    write_spy.clear()

    sess.agent.history.append({"role": "assistant", "content": "a1"})
    store.save(sess)

    assert len(write_spy) == 1
    loaded = _reload_from_disk(store, "livehist")
    assert loaded.agent_history == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a1"},
    ]


# ---------------------------------------------------------------------------
# delete() clears write state so re-created sessions are written again
# ---------------------------------------------------------------------------

def test_delete_then_recreate_same_content_writes(store, write_spy):
    sess = store.create_main("reborn")
    sess.messages = [{"type": "user", "text": "v1"}]
    store.save(sess)
    store.delete("reborn")
    assert not os.path.exists(_path(store, "reborn.jsonl"))

    write_spy.clear()
    sess2 = store.create_main("reborn")
    sess2.messages = [{"type": "user", "text": "v1"}]  # identical content
    store.save(sess2)

    assert len(write_spy) == 1, "state cleared on delete: identical save must rewrite"
    assert _reload_from_disk(store, "reborn").messages == [{"type": "user", "text": "v1"}]


def test_delete_subagent_then_recreate_same_content_writes(store, write_spy):
    sub = store.create_subagent(parent_id="p1", subagent_id="sub1")
    sub.messages = [{"type": "user", "text": "v1"}]
    store.save(sub)
    store.delete("sub1")
    assert not os.path.exists(os.path.join(store.sessions_dir, "p1.subagents", "sub1.jsonl"))

    write_spy.clear()
    sub2 = store.create_subagent(parent_id="p1", subagent_id="sub1")
    sub2.messages = [{"type": "user", "text": "v1"}]
    store.save(sub2)

    assert len(write_spy) == 1
    assert _reload_from_disk(store, "sub1").messages == [{"type": "user", "text": "v1"}]


def test_delete_main_clears_cascaded_subagent_state(store):
    sub = store.create_subagent(parent_id="pm", subagent_id="psub")
    sub.messages = [{"type": "user", "text": "v1"}]
    store.save(sub)
    main = store.create_main("pm")
    main.messages = [{"type": "user", "text": "x"}]
    store.save(main)
    assert len(store._session_write_state) == 2

    store.delete("pm")

    assert store._session_write_state == {}


# ---------------------------------------------------------------------------
# save_async still works through the same path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_async_persists(store, write_spy):
    sess = store.create_main("async1")
    sess.messages = [{"type": "user", "text": "hello"}]
    await store.save_async(sess)
    await store.save_async(sess)  # no-op

    assert len(write_spy) == 1
    loaded = _reload_from_disk(store, "async1")
    assert loaded.messages == [{"type": "user", "text": "hello"}]


# ---------------------------------------------------------------------------
# Bytes on disk remain valid, ordered JSONL after mixed saves
# ---------------------------------------------------------------------------

def test_file_is_valid_jsonl_after_mixed_saves(store):
    sess = store.create_main("jsonl")
    for i in range(5):
        sess.add_event({"type": "user", "text": f"q{i}"})
        sess.add_event({"type": "bot", "text": f"a{i}", "final": True})
        store.save(sess)
    store.save(sess)  # no-op

    lines = _read(store, "jsonl.jsonl").splitlines()
    assert lines[0].startswith('{"_type": "meta"')
    assert lines[0].endswith("}")
    meta = json.loads(lines[0])
    msg_lines = [json.loads(line) for line in lines[1:]]
    assert all(entry["_type"] == "msg" for entry in msg_lines)
    assert meta["id"] == "jsonl"
    assert len(msg_lines) == 10
