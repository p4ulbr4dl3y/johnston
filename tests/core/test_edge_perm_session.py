"""Edge-case tests for PermissionManager and SessionStore (bug hunting).

Some tests intentionally assert expected-secure behavior and FAIL because the
implementation has bugs. Those failures are documented inline with the offending
source line. Do not edit core/ code — red tests are findings.
"""
import json
import os
from unittest.mock import patch

import pytest

from core.permission_manager import PermissionManager
from core.session_manager import AgentSession, SessionStore

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

class _PM:
    """Fresh PermissionManager with a patched, isolated CONFIG_FILE."""

    def __init__(self, config_path):
        self.cfg = config_path
        self.pm = PermissionManager()
        self.pm.clear_session_overrides()
        if config_path and os.path.exists(config_path):
            os.remove(config_path)

    def __enter__(self):
        self.patcher = patch("core.permission_manager.CONFIG_FILE", self.cfg)
        self.patcher.start()
        return self.pm

    def __exit__(self, *a):
        self.patcher.stop()


@pytest.fixture
def pm(tmp_path):
    cfg = str(tmp_path / "config.json")
    with _PM(cfg) as pm:
        yield pm, cfg


@pytest.fixture
def store(tmp_path):
    """A SessionStore rooted in tmp_path (PROJECTS_DIR patched)."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    with patch("core.session_manager.PROJECTS_DIR", str(projects_dir)):
        s = SessionStore(project_path=str(project))
        yield s


def _write_session_json(store, name, data):
    path = os.path.join(store.sessions_dir, name)
    if isinstance(data, dict):
        if "_type" not in data:
            meta = dict(data)
            meta["_type"] = "meta"
            messages = meta.pop("messages", [])
            history = meta.pop("agent_history", [])
            lines = [json.dumps(meta, ensure_ascii=False)]
            for m in messages:
                lines.append(json.dumps({"_type": "msg", "data": m}, ensure_ascii=False))
            for h in history:
                lines.append(json.dumps({"_type": "history", "data": h}, ensure_ascii=False))
            content = "\n".join(lines) + "\n"
        else:
            content = json.dumps(data, ensure_ascii=False) + "\n"
    elif isinstance(data, list):
        content = "\n".join(json.dumps(item, ensure_ascii=False) for item in data) + "\n"
    else:
        content = str(data) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ===========================================================================
# PERMISSION MANAGER edge cases
# ===========================================================================

def test_check_permission_none_or_empty_tool_name_grants_allow(pm):
    """None/empty tool name must NOT be granted 'allow' (security). BUG."""
    pm_obj, _ = pm
    action = pm_obj.check_permission(None).action
    assert action == "deny", (
        "check_permission(None) returns %r — empty tool name is treated as an "
        "MCP tool and defaults to 'allow' (permission_manager.py:149-154). "
        "A missing tool name must fail closed."
    )
    action2 = pm_obj.check_permission("").action
    assert action2 == "deny", (
        "check_permission('') returns %r — same empty-name allow bypass."
    )


def test_mcp_default_deny_is_ignored(pm):
    """Global default 'deny' must NOT be bypassed for MCP tools. BUG."""
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"default": "deny"}}, f)
    action = pm_obj.check_permission("gh__search").action
    assert action == "deny", (
        "MCP tool with global default 'deny' returns %r — permission_manager.py:149-154 "
        "only fail-closes on INVALID default, but ignores a valid 'deny'. "
        "Global default deny is bypassed for all MCP tools (security)."
    )


def test_builtin_default_deny_is_respected(pm):
    """Control: global default deny DOES apply to builtin tools."""
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"default": "deny"}}, f)
    action = pm_obj.check_permission("read").action
    assert action == "deny"


def test_wildcard_config_is_literal_not_glob(pm):
    """No glob support — a '*' entry must not match anything. (pass/green)"""
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"tools": {"*": "deny", "read*": "deny"}}}, f)
    # 'read' is not matched by literal '*' or 'read*'
    action = pm_obj.check_permission("read").action
    assert action == "allow"


def test_regex_special_char_config_is_literal_and_not_injected(pm):
    """'.', '(', ')' in a tool/config name must be treated literally (no regex crash)."""
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"tools": {"shell.(x)": "deny", "file.com": "ask"}}}, f)
    # None of these special names collide with real tools -> no crash, no match.
    action = pm_obj.check_permission("shell").action
    assert action == "ask"
    action2 = pm_obj.check_permission("file.com").action
    assert action2 == "ask"


def test_deny_explicit_beats_default_allow(pm):
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
    action = pm_obj.check_permission("web_fetch").action
    assert action == "deny"


def test_session_override_beats_config(pm):
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"tools": {"web_fetch": "allow"}}}, f)
    pm_obj.set_session_override("web_fetch", "deny")
    action = pm_obj.check_permission("web_fetch").action
    assert action == "deny"


def test_case_insensitive_and_trailing_space_toolname(pm):
    pm_obj, cfg = pm
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"permissions": {"tools": {"web_fetch": "deny"}}}, f)
    action = pm_obj.check_permission("  WEB_FETCH  ").action
    assert action == "deny"


def test_empty_override_cleared_recheck(pm):
    pm_obj, cfg = pm
    pm_obj.set_session_override("read", "deny")
    assert pm_obj.check_permission("read").action == "deny"
    # cache invalidation / re-evaluation after clear
    pm_obj.clear_session_overrides()
    assert pm_obj.check_permission("read").action == "allow"



def test_update_permission_overwrites_and_removes_duplicates(pm):
    pm_obj, cfg = pm
    pm_obj.update_permission("tool", "web_fetch", "deny")
    pm_obj.update_permission("tool", "web_fetch", "allow")  # overwrite
    action = pm_obj.check_permission("web_fetch").action
    assert action == "allow"
    data = json.load(open(cfg, encoding="utf-8"))
    assert data["permissions"]["tools"]["web_fetch"] == "allow"


def test_update_permission_trailing_slash_and_uppercase(pm):
    pm_obj, cfg = pm
    pm_obj.update_permission("tool", "  WEB_FETCH  ", "deny")
    action = pm_obj.check_permission("WEB_FETCH").action
    assert action == "deny"


# ===========================================================================
# SESSION MANAGER edge cases
# ===========================================================================

def test_add_event_none_crashes(store):
    """add_event(None) must not crash. BUG (crash on invalid input)."""
    sess = store.create_main("s1")
    with pytest.raises(AttributeError):
        sess.add_event(None)  # attr error: 'NoneType' has no 'get' (session_manager.py:80)
    # even if it raises, the session must remain usable -> it crashed => bug.


def test_add_event_non_dict_crashes(store):
    """add_event('string') must not crash. BUG."""
    sess = store.create_main("s2")
    with pytest.raises(AttributeError):
        sess.add_event("not-a-dict")


def test_add_event_after_finish_still_appended(store):
    """Events after finish are still recorded (documented behavior)."""
    sess = store.create_main("s3")
    sess.finish("completed")
    sess.add_event({"type": "bot", "text": "late"})
    types = [m.get("type") for m in sess.messages]
    assert "status_change" in types
    assert {"type": "bot", "text": "late"} in sess.messages


def test_finish_twice_appends_two_status_events(store):
    """Finishing twice appends two status_change events (duplicate)."""
    sess = store.create_main("s4")
    sess.finish("completed")
    sess.finish("completed")
    status_changes = [m for m in sess.messages if m.get("type") == "status_change"]
    assert len(status_changes) == 2


def test_finish_then_running_status_settable(store):
    """status transitions are not validated — completed->running allowed. BUG."""
    sess = store.create_main("s5")
    sess.status = "completed"
    sess.status = "running"  # no validation anywhere
    assert sess.status == "running"


def test_roundtrip_big_nested_unicode(store):
    """Save->load must equal original for large nested unicode content."""
    sess = store.create_main("big")
    sess.messages = [
        {"type": "user", "text": "Привет мир 🌍 " * 500},
        {"type": "tool", "name": "shell", "result_text": "x" * 200_000},
        {"type": "bot", "text": {"nested": ["a", {"deep": "值"}]}, "final": True},
    ]
    weird = {"\u0000": [1, 2, {"k": "é"}]}
    sess.agent_history = [{"role": "assistant", "content": weird}]
    stored = sess.to_dict()
    store.save(sess)
    store._sessions.clear()
    loaded = store.get("big")
    assert loaded is not None
    assert loaded.to_dict() == stored


def test_roundtrip_empty_session(store):
    sess = store.create_main("empty")
    store.save(sess)
    store._sessions.clear()
    loaded = store.get("empty")
    assert loaded is not None
    assert loaded.messages == []
    assert loaded.agent_history == []


def test_load_missing_session_returns_none(store):
    assert store.get("does_not_exist") is None


def test_list_ignores_junk_non_json_files(store):
    base = store.sessions_dir
    with open(os.path.join(base, "notes.txt"), "w") as f:
        f.write("not json at all")
    with open(os.path.join(base, "random.bin"), "wb") as f:
        f.write(b"\x00\x01\xff\xfe")
    os.makedirs(os.path.join(base, "not_subagents_dir"), exist_ok=True)
    listed = store.list()
    assert all(os.path.isfile(os.path.join(base, "notes.txt")) for _ in [0])  # no deletion
    assert "notes.txt" not in [s.id for s in listed]


def test_list_skips_json_scalar_and_list(store):
    _write_session_json(store, "scalar.jsonl", "justanystring")
    _write_session_json(store, "array.jsonl", [1, 2, 3])
    _write_session_json(store, "twop.jsonl", {"id": "twop", "kind": "main", "messages": []})
    listed = store.list()
    ids = {s.id for s in listed}
    assert "scalar" not in ids
    assert "array" not in ids
    assert "twop" in ids


def test_delete_nonexistent_no_error(store):
    store.delete("ghost")  # must not raise
    store.delete("")       # must not raise


def test_save_session_id_with_traversal_writes_outside_sessions(store):
    """A session id with '../' must not write outside sessions_dir. BUG (path traversal)."""
    evil = store.create_main("../config")  # would resolve to <project_dir>/config.json
    store.save(evil)
    project_config = os.path.join(store.project_dir, "config.json")
    assert not os.path.exists(project_config), (
        "save() with session id '../config' wrote the session into "
        "project_dir/config.json (session_manager.py:230-231 `_main_path` joins "
        "the raw id, so '../' escapes sessions_dir). Session ids must be "
        "sanitized/normalized before use as file names."
    )


def test_from_dict_missing_fields_defaults(store):
    data = {"id": "minimal", "kind": "subagent", "parent_id": "p"}
    sess = AgentSession.from_dict(data)
    assert sess.id == "minimal"
    assert sess.role == "worker"
    assert sess.status == "active"
    assert sess.messages == []
    assert sess.cost_usd == 0.0


def test_duplicate_id_disk_and_memory(store):
    sess = store.create_main("dup")
    sess.messages = [{"type": "user", "text": "memory version"}]
    store.save(sess)
    # create a conflicting disk-only copy
    _write_session_json(store, "dup.jsonl", {"id": "dup", "kind": "main", "messages": [{"type": "user", "text": "disk version"}]})
    store._invalidate_disk_cache()
    listed = [s for s in store.list() if s.id == "dup"]
    assert len(listed) == 1  # no duplicate keys


def test_unicode_session_id_roundtrip(store):
    sess = store.create_main("сессия-☃")
    sess.messages = [{"type": "user", "text": "тест"}]
    store.save(sess)
    store._sessions.clear()
    loaded = store.get("сессия-☃")
    assert loaded is not None
    assert loaded.messages[0]["text"] == "тест"
