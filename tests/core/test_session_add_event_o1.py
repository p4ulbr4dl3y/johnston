"""Performance fix M5: AgentSession.add_event O(1)-amortized tool-result matching.

The old implementation rescanned self.messages from index 0 for every
tool_result event (O(n) per result, O(n^2) per tool-heavy turn). A live-only
forward pointer (_next_unmatched_tool_idx) now skips already-matched/non-
matchable messages. These tests pin the exact old-scan behavior across the
pointer's lifetimes: ordered matching, out-of-order results, truncation/rewind
(which replaces self.messages with a prefix), and from_file deserialization,
plus that the tracker is never persisted.
"""
import json

import pytest

from core.domain.entities.session import AgentSession, MessageType


def _add_tool(sess: AgentSession, name: str) -> None:
    sess.add_event({"type": MessageType.TOOL, "tool_type": "read", "target": name, "args": {"path": name}})


def _add_result(sess: AgentSession, text: str) -> None:
    sess.add_event({"type": MessageType.TOOL, "result_text": text, "status": "done"})


@pytest.fixture
def sess() -> AgentSession:
    return AgentSession("s_o1", prompt="test")


def _tool_msgs(sess: AgentSession):
    return [m for m in sess.messages if m.get("type") == MessageType.TOOL]


# -- (a) ordered matching over many tool calls ---------------------------


def test_tool_results_match_in_order_over_many_tools(sess):
    n = 100
    pointer_progress = []
    for i in range(n):
        _add_tool(sess, f"{i}.py")
        if i % 3 == 0:  # interleave unrelated messages to force scans past them
            sess.add_event({"type": "thinking", "text": f"step {i}"})
        _add_result(sess, f"content_{i}")
        pointer_progress.append(sess._next_unmatched_tool_idx)

    msgs = _tool_msgs(sess)
    assert len(msgs) == n
    for i, m in enumerate(msgs):
        assert m["target"] == f"{i}.py"
        assert m["result_text"] == f"content_{i}"
    # O(1) amortized: each result advances the pointer onto a message never
    # scanned before (strictly increasing), so no message is ever re-scanned.
    assert pointer_progress == sorted(pointer_progress)
    assert len(set(pointer_progress)) == len(pointer_progress)
    assert sess._next_unmatched_tool_idx <= len(sess.messages)


def test_out_of_order_results_match_first_unmatched(sess):
    """Results carry no tool id: the old scan matched the FIRST unmatched tool
    message, so an out-of-order result landed on the oldest pending tool.
    The pointer scan must reproduce that byte-identically."""
    _add_tool(sess, "a.py")
    _add_tool(sess, "b.py")
    _add_result(sess, "result_for_b")  # lands on a.py (first unmatched)
    _add_result(sess, "result_for_a")  # lands on b.py
    msgs = _tool_msgs(sess)
    assert [m["target"] for m in msgs] == ["a.py", "b.py"]
    assert msgs[0]["result_text"] == "result_for_b"
    assert msgs[1]["result_text"] == "result_for_a"


def test_result_without_target_appends(sess):
    """Fallback preserved: a tool_result with no pending tool message is
    appended as a standalone message (old else-branch behavior)."""
    sess.add_event({"type": "user", "text": "hi"})
    _add_result(sess, "orphan")
    assert len(_tool_msgs(sess)) == 1
    assert _tool_msgs(sess)[0]["result_text"] == "orphan"
    # The appended orphan carries result_text (non-matchable); the pointer
    # points at it, so the next result can't land on it either.
    assert _tool_msgs(sess)[0] is sess.messages[sess._next_unmatched_tool_idx]


# -- (b) truncation / rewind ---------------------------------------------


def test_rewind_to_empty_clamps_pointer(sess):
    """_truncate_transcript(seq_idx=0) replaces messages with []; the pointer
    must clamp and subsequent results still behave like a from-0 scan."""
    _add_tool(sess, "1.py")
    _add_result(sess, "r1")
    _add_tool(sess, "2.py")
    assert sess._next_unmatched_tool_idx > 0
    sess.messages = []  # exactly what _truncate_transcript does for seq_idx 0
    _add_result(sess, "no_target")  # no unmatched tool below the clamp → append
    _add_tool(sess, "3.py")
    _add_result(sess, "r3")
    assert sess.messages[0]["result_text"] == "no_target"  # orphaned result
    assert sess.messages[-1]["target"] == "3.py"
    assert sess.messages[-1]["result_text"] == "r3"


def test_rewind_mid_session_keeps_tracker_correct(sess):
    """Truncate to a mid-transcript prefix (pointer beyond and inside the kept
    region) and keep adding tool calls/results: matched prefixes keep their
    result_text, so the pointer math must remain identical to a from-0 scan."""
    sess.add_event({"type": "user", "text": "u1"})
    _add_tool(sess, "1.py")
    _add_result(sess, "r1")
    _add_tool(sess, "2.py")
    _add_result(sess, "r2")
    sess.add_event({"type": "user", "text": "u2"})
    _add_tool(sess, "3.py")  # left unmatched on purpose
    assert sess._next_unmatched_tool_idx > 0

    # Rewind to the start of the "u2" turn: keeps [u1, 1.py, r1, 2.py, r2].
    cutoff = next(i for i, m in enumerate(sess.messages) if m.get("text") == "u2")
    sess.messages = sess.messages[:cutoff]  # _truncate_transcript prefix drop
    assert sess._next_unmatched_tool_idx <= len(sess.messages)

    _add_tool(sess, "4.py")
    _add_result(sess, "r4")
    msgs = _tool_msgs(sess)
    assert [m["target"] for m in msgs] == ["1.py", "2.py", "4.py"]
    assert msgs[-1]["result_text"] == "r4"
    assert msgs[0]["result_text"] == "r1"
    assert msgs[1]["result_text"] == "r2"


def test_rewind_keeping_unmatched_tool_below_old_end(sess):
    """Truncation that keeps a still-unmatched tool message (cutoff after it)
    must leave it matchable: the pointer sits before it."""
    sess.add_event({"type": "user", "text": "u1"})
    _add_tool(sess, "1.py")
    _add_result(sess, "r1")
    _add_tool(sess, "2.py")  # unmatched, kept by the truncation
    sess.add_event({"type": "thinking", "text": "later"})  # dropped tail
    sess.messages = sess.messages[:-1]  # drop the tail, keep unfinished tool
    _add_result(sess, "r2")
    msgs = _tool_msgs(sess)
    assert msgs[1]["target"] == "2.py"
    assert msgs[1]["result_text"] == "r2"


# -- (c) from_file round-trip --------------------------------------------


def test_from_file_roundtrip_matches_unmatched_tools(tmp_path, sess):
    _add_tool(sess, "1.py")
    _add_tool(sess, "2.py")
    fpath = tmp_path / "session.jsonl"
    with open(fpath, "w", encoding="utf-8") as f:
        for line in sess.to_jsonl_lines():
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    loaded = AgentSession.from_file(str(fpath))
    assert loaded is not None
    assert loaded._next_unmatched_tool_idx == 0  # live-only state resets on load
    assert len(_tool_msgs(loaded)) == 2
    _add_result(loaded, "r1")
    _add_result(loaded, "r2")
    msgs = _tool_msgs(loaded)
    assert msgs[0]["result_text"] == "r1"
    assert msgs[1]["result_text"] == "r2"
    assert loaded._next_unmatched_tool_idx == len(loaded.messages)


# -- (d) tracker never persisted -----------------------------------------


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def test_tracker_not_persisted(sess):
    sess._next_unmatched_tool_idx = 7  # make it non-trivial
    lines = sess.to_jsonl_lines()
    assert "next_unmatched" not in json.dumps(lines)
    assert "next_unmatched" not in json.dumps(sess.to_dict())
    assert not any("_next_unmatched_tool_idx" in k for k in _walk_keys(lines))
    assert not any("_next_unmatched_tool_idx" in k for k in _walk_keys(sess.to_dict()))
