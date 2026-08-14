"""Edge-case tests for core/subagent_stream.py — hunting for implementation bugs."""

import asyncio

import pytest

from core.session_manager import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_ERROR,
    AgentSession,
)
from core.subagent_stream import (
    apply_subagent_role,
    cancel_running_subagents,
    merge_subagent_metrics,
    record_subagent_step,
    run_subagent_stream_bg,
)


def make_session(description="d", status="running"):
    s = AgentSession(session_id="sub-1", kind="subagent", parent_id="main-1", description=description, status=status)
    return s


# ---------------------------------------------------------------------------
# record_subagent_step
# ---------------------------------------------------------------------------


class TestRecordShortTuples:
    def test_empty_tuple_does_not_raise(self):
        s = make_session()
        record_subagent_step((), s, [""])
        assert s.messages == []

    def test_single_element_tool(self):
        s = make_session()
        record_subagent_step(("tool",), s, [""])
        assert s.messages[-1] == {"type": "tool", "tool_type": "", "target": "", "args": {}}

    def test_bot_delta_without_value_uses_empty(self):
        s = make_session()
        acc = [""]
        record_subagent_step(("bot_delta",), s, acc)
        assert acc[0] == ""  # val1 defaults to "" not None

    def test_thinking_end_without_value(self):
        s = make_session()
        record_subagent_step(("thinking_end",), s, [""])
        assert s.messages[-1]["duration"] == 0.0


class TestToolTargs:
    def test_non_dict_val3_becomes_empty_args(self):
        s = make_session()
        record_subagent_step(("tool", "shell", "/tmp", "notadict"), s, [""])
        assert s.messages[-1]["args"] == {}

    def test_dict_val3_preserved(self):
        s = make_session()
        record_subagent_step(("tool", "shell", "/tmp", {"cwd": "/"}), s, [""])
        assert s.messages[-1]["args"] == {"cwd": "/"}


class TestThinkingEndDuration:
    @pytest.mark.parametrize("val", ["abc", None, "nan", "inf"])
    def test_non_numeric_or_nonfinite_becomes_zero(self, val):
        s = make_session()
        record_subagent_step(("thinking_end", val, "done"), s, [""])
        assert s.messages[-1]["duration"] == 0.0

    def test_valid_float_preserved(self):
        s = make_session()
        record_subagent_step(("thinking_end", "3.5", "done"), s, [""])
        assert s.messages[-1]["duration"] == 3.5


class TestBotDeltaNone:
    def test_bot_delta_none_val1_raises_typeerror(self):
        # BUG: acc[0] + None -> TypeError. val1 defaults to None via len(step)>1 check.
        s = make_session()
        acc = [""]
        with pytest.raises(TypeError):
            record_subagent_step(("bot_delta", None), s, acc)

    def test_bot_text_none_val1_is_ok(self):
        s = make_session()
        acc = [""]
        record_subagent_step(("bot_text", None), s, acc)
        assert acc[0] is None
        assert s.messages[-1] == {"type": "bot", "text": None, "final": True}

    def test_outro_none_val1_is_ok(self):
        s = make_session()
        acc = [""]
        record_subagent_step(("outro", None), s, acc)
        assert acc[0] is None


class TestUnknownAndSemantics:
    def test_unknown_step_type_ignored(self):
        s = make_session()
        record_subagent_step(("completely_unknown", "x", "y"), s, [""])
        assert s.messages == []

    def test_bot_delta_accumulates(self):
        s = make_session()
        acc = [""]
        record_subagent_step(("bot_delta", "Hel"), s, acc)
        record_subagent_step(("bot_delta", "lo"), s, acc)
        assert acc[0] == "Hello"
        assert s.messages[-1]["text"] == "Hello"

    def test_bot_text_overwrites_accumulator(self):
        s = make_session()
        acc = [""]
        record_subagent_step(("bot_delta", "partial"), s, acc)
        record_subagent_step(("bot_text", "final"), s, acc)
        assert acc[0] == "final"


# ---------------------------------------------------------------------------
# merge_subagent_metrics
# ---------------------------------------------------------------------------


class FakeAgent:
    def __init__(self):
        self.tokens_input = 0
        self.tokens_output = 0
        self.total_tokens = 0
        self.cost_usd = 0.0

    def get_metrics(self):
        """Mirrors core.base_provider.agent.get_metrics contract used by the footer."""
        return {
            "total_tokens": self.total_tokens,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "context_used": 0,
            "context": "128k",
            "context_limit": 128000,
            "cost_usd": self.cost_usd,
        }


class _FakeApp:
    def __init__(self, agent=None):
        self.agent = agent


class _FakeCtx:
    def __init__(self, app):
        self.app = app


class TestMergeMetrics:
    def test_subagent_without_metric_attrs_uses_default(self):
        class Dummy:
            pass

        sub = Dummy()  # no tokens_* attrs at all, but has __dict__
        main = FakeAgent()
        ctx = _FakeCtx(_FakeApp(main))
        merge_subagent_metrics(sub, ctx)
        assert main.tokens_input == 0

    def test_context_app_agent_none_is_noop(self):
        ctx = _FakeCtx(_FakeApp(None))
        merge_subagent_metrics(object(), ctx)  # should not raise

    def test_context_app_none_is_noop(self):
        ctx = _FakeCtx(None)
        merge_subagent_metrics(object(), ctx)  # should not raise

    def test_negative_delta_not_merged(self):
        main = FakeAgent()
        main.tokens_input = 100
        sub = FakeAgent()
        sub.tokens_input = 50
        sub._merged_tokens_input = 100  # cur (50) < last (100) -> delta negative -> skipped
        ctx = _FakeCtx(_FakeApp(main))
        merge_subagent_metrics(sub, ctx)
        assert main.tokens_input == 100

    def test_bool_is_not_a_number(self):
        sub = FakeAgent()
        sub.tokens_input = True  # bool excluded by _val
        main = FakeAgent()
        ctx = _FakeCtx(_FakeApp(main))
        merge_subagent_metrics(sub, ctx)
        assert main.tokens_input == 0

    def test_double_call_no_double_count(self):
        main = FakeAgent()
        sub = FakeAgent()
        sub.tokens_input = 10
        sub.cost_usd = 0.5
        ctx = _FakeCtx(_FakeApp(main))

        merge_subagent_metrics(sub, ctx)
        assert main.tokens_input == 10

        sub.tokens_input = 15  # grow by 5
        sub.cost_usd = 0.7
        merge_subagent_metrics(sub, ctx)
        assert main.tokens_input == 15  # not 25
        assert main.cost_usd == 0.7

    def test_float_and_int_metrics(self):
        main = FakeAgent()
        sub = FakeAgent()
        sub.tokens_input = 3.0  # float
        sub.cost_usd = 0.25
        ctx = _FakeCtx(_FakeApp(main))
        merge_subagent_metrics(sub, ctx)
        assert main.tokens_input == 3.0
        assert main.cost_usd == 0.25


# ---------------------------------------------------------------------------
# run_subagent_stream_bg
# ---------------------------------------------------------------------------


class FakeSubagent:
    def __init__(self, steps=None, exc=None):
        self._steps = steps or []
        self._exc = exc
        self.tokens_input = 0
        self.tokens_output = 0
        self.total_tokens = 0
        self.cost_usd = 0.0

    async def stream_steps(self, *a, **k):
        for st in self._steps:
            yield st
        if self._exc is not None:
            raise self._exc


class FakeStore:
    def __init__(self):
        self.saved = []

    def save(self, sess):
        self.saved.append(sess)


class FakeCtx:
    def __init__(self):
        self.app = _FakeApp(FakeAgent())
        self.refreshed = 0
        self.messages = []

    def refresh_status(self):
        self.refreshed += 1

    def trigger_ai_response(self, msg):
        self.messages.append(msg)


class FakeStreamCompleteSubagent(FakeSubagent):
    pass


class TestRunStream:
    @pytest.mark.asyncio
    async def test_success_finish_completed_and_saved(self):
        sub = FakeSubagent(steps=[("bot_text", "hi")])
        sess = make_session()
        store = FakeStore()
        ctx = FakeCtx()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, store)
        assert result == "hi"
        assert sess.status == STATUS_COMPLETED  # uses string "completed"
        assert store.saved == [sess]

    @pytest.mark.asyncio
    async def test_cancelled_error_sets_cancelled_status(self):
        sub = FakeSubagent(exc=asyncio.CancelledError())
        sess = make_session()
        ctx = FakeCtx()
        store = FakeStore()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, store)
        assert result == "[Subagent cancelled]"
        assert sess.status == STATUS_CANCELLED
        assert store.saved == [sess]

    @pytest.mark.asyncio
    async def test_generic_exception_sets_error_status_with_prefix(self):
        sub = FakeSubagent(exc=RuntimeError("boom"))
        sess = make_session()
        ctx = FakeCtx()
        store = FakeStore()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, store, error_prefix="MyPrefix")
        assert result == "[MyPrefix: boom]"
        assert sess.status == STATUS_ERROR
        assert store.saved == [sess]

    @pytest.mark.asyncio
    async def test_cleanup_fn_raises_does_not_mask_result(self):
        sub = FakeSubagent(steps=[("bot_text", "ok")])
        sess = make_session()
        ctx = FakeCtx()
        store = FakeStore()

        def bad_cleanup(acc):
            raise RuntimeError("cleanup broke")

        result = await run_subagent_stream_bg(sub, "p", sess, ctx, store, cleanup_fn=bad_cleanup)
        assert result == "ok"
        assert sess.status == STATUS_COMPLETED

    @pytest.mark.asyncio
    async def test_truncate_true_with_empty_acc_fallback(self):
        sub = FakeSubagent(steps=[])
        sess = make_session()
        ctx = FakeCtx()
        store = FakeStore()
        await run_subagent_stream_bg(
            sub, "p", sess, ctx, store, notification_template="notify {result_text}", truncate_result=True
        )
        assert ctx.messages and ctx.messages[0] == "notify Completed with no text output."

    @pytest.mark.asyncio
    async def test_notification_template_braces_in_description_safe(self):
        # .format only interprets braces in the TEMPLATE, not in substituted
        # values, so braces inside description are safe (no KeyError).
        sub = FakeSubagent(steps=[("bot_text", "hi")])
        sess = make_session(description="has {brace} here")
        ctx = FakeCtx()
        store = FakeStore()
        await run_subagent_stream_bg(sub, "p", sess, ctx, store, notification_template="{description}: {result_text}")
        assert ctx.messages and ctx.messages[0] == "has {brace} here: hi"

    @pytest.mark.asyncio
    async def test_metrics_merged_into_parent(self):
        sub = FakeSubagent(steps=[("bot_text", "hi")])
        sub.tokens_input = 42
        sess = make_session()
        ctx = FakeCtx()
        store = FakeStore()
        await run_subagent_stream_bg(sub, "p", sess, ctx, store)
        assert ctx.app.agent.tokens_input == 42

    @pytest.mark.asyncio
    async def test_merged_metrics_visible_via_parent_get_metrics(self):
        """End-to-end: subagent token/cost merge shows up in the parent agent's
        get_metrics() — the exact contract the main footer reads for row2."""
        sub = FakeSubagent(steps=[("bot_text", "hi")])
        sub.tokens_input = 24
        sub.tokens_output = 18
        sub.total_tokens = 42
        sub.cost_usd = 0.0075
        sess = make_session()
        store = FakeStore()

        parent_agent = FakeAgent()
        ctx = FakeCtx()  # has refresh_status; reuse its FakeAgent holder
        ctx.app = _FakeApp(parent_agent)

        await run_subagent_stream_bg(sub, "p", sess, ctx, store)

        metrics = parent_agent.get_metrics()
        assert metrics["tokens_input"] == 24
        assert metrics["tokens_output"] == 18
        assert metrics["total_tokens"] == 42
        assert metrics["cost_usd"] == 0.0075
        # Merger bookkeeping records the already-merged totals on the subagent,
        # so a second run of the merger (e.g. re-finish) is a no-op.
        assert sub._merged_tokens_input == 24
        assert sub._merged_total_tokens == 42

    @pytest.mark.asyncio
    async def test_return_acc_first_value(self):
        sub = FakeSubagent(steps=[("bot_text", "hello"), ("bot_delta", " world")])
        sess = make_session()
        ctx = FakeCtx()
        store = FakeStore()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, store)
        assert result == "hello world"
        assert sess.status == STATUS_COMPLETED

    @pytest.mark.asyncio
    async def test_queued_messages_drained_in_order(self):
        class QueueSubagent(FakeSubagent):
            async def stream_steps(self, *a, **k):
                yield ("bot_text", f"reply:{a[0]}")

        sub = QueueSubagent()
        sess = make_session()
        sess.pending_messages = ["second", "third"]
        ctx = FakeCtx()
        store = FakeStore()
        result = await run_subagent_stream_bg(sub, "first", sess, ctx, store)
        # One stream task processes all queued messages, accumulating the last reply.
        assert result == "reply:third"
        assert sess.status == STATUS_COMPLETED
        assert sess.pending_messages == []
        # Each message was processed and saved.
        assert len(store.saved) == 3

    @pytest.mark.asyncio
    async def test_queued_drain_keeps_running_until_busy_returns(self):
        class QueueSubagent(FakeSubagent):
            async def stream_steps(self, *a, **k):
                yield ("bot_text", f"reply:{a[0]}")

        sub = QueueSubagent()
        sess = make_session()
        # Simulate a follow-up arriving mid-completion of the first message.
        sess.pending_messages = ["mid"]
        ctx = FakeCtx()
        store = FakeStore()
        result = await run_subagent_stream_bg(sub, "first", sess, ctx, store)
        assert result == "reply:mid"
        assert sess.status == STATUS_COMPLETED
        assert sess.pending_messages == []

    @pytest.mark.asyncio
    async def test_queued_message_appended_after_first_save_drained(self):
        class QueueSubagent(FakeSubagent):
            def __init__(self):
                self.count = 0

            async def stream_steps(self, *a, **k):
                self.count += 1
                if self.count == 1:
                    # First message ran; follow-up queued after it finished streaming.
                    self._sess.pending_messages.append("late")
                yield ("bot_text", f"reply:{a[0]}")

        sub = QueueSubagent()
        sess = make_session()
        sub._sess = sess
        ctx = FakeCtx()
        store = FakeStore()
        result = await run_subagent_stream_bg(sub, "first", sess, ctx, store)
        assert result == "reply:late"
        assert sess.status == STATUS_COMPLETED
        assert sess.pending_messages == []


# ---------------------------------------------------------------------------
# _safe_save / save-failure propagation
# ---------------------------------------------------------------------------


class FailingStore:
    def save(self, sess):
        raise OSError("disk full")


class TestSafeSaves:
    def test_error_logged_not_swallowed(self, caplog):
        import logging as _logging

        from core import subagent_stream

        s = make_session()
        with caplog.at_level(_logging.ERROR):
            with pytest.raises(OSError):
                subagent_stream._safe_save(FailingStore(), s)
        assert "Failed to save subagent session" in caplog.text

    def test_error_propagates_to_caller(self):
        from core import subagent_stream

        s = make_session()
        with pytest.raises(OSError):
            subagent_stream._safe_save(FailingStore(), s)

    @pytest.mark.asyncio
    async def test_save_failure_not_left_completed(self):
        sub = FakeSubagent(steps=[("bot_text", "hi")])
        sess = make_session()
        ctx = FakeCtx()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, FailingStore())
        assert sess.status == STATUS_ERROR  # never left COMPLETED
        assert "Subagent error" in result

    @pytest.mark.asyncio
    async def test_save_failure_error_status_has_oserror(self):
        sub = FakeSubagent(steps=[("bot_text", "hi")])
        sess = make_session()
        ctx = FakeCtx()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, FailingStore())
        assert "disk full" in result

    @pytest.mark.asyncio
    async def test_save_failure_cancelled_keeps_cancelled_status(self):
        sub = FakeSubagent(exc=asyncio.CancelledError())
        sess = make_session()
        ctx = FakeCtx()
        result = await run_subagent_stream_bg(sub, "p", sess, ctx, FailingStore())
        assert sess.status == STATUS_CANCELLED
        assert "failed to save cancelled session" in result


# ---------------------------------------------------------------------------
# apply_subagent_role
# ---------------------------------------------------------------------------


class FakeRole:
    def __init__(
        self,
        key="worker",
        prompt="worker prompt",
        model="",
        provider="",
        scope="any",
        read_only=False,
        disallowed_tools=None,
        allowed_tools=None,
    ):
        self.key = key
        self.system_prompt = prompt
        self.prompt = prompt
        self.model = model
        self.provider = provider
        self.scope = scope
        self.read_only = read_only
        self.disallowed_tools = disallowed_tools or []
        self.allowed_tools = allowed_tools or []

    def is_tool_allowed(self, name):
        return None


class FakeSubagentAgent:
    def __init__(self, tools=None, provider_key=""):
        self.tools = tools
        self.provider_key = provider_key
        self.role = ""
        self.system_prompt = ""
        self.model = ""
        self.allow_task = True


def _tool(name):
    return {"type": "function", "function": {"name": name, "description": f"desc {name}"}}


class TestApplyRole:
    def _fake_registry(self, monkeypatch, roles):
        from core import role_registry

        class FakeReg:
            def load_roles(self, project_dir=None):
                pass

            def get_role(self, key):
                return roles.get(key, roles.get("worker"))

        monkeypatch.setattr(role_registry.RoleRegistry, "get_instance", lambda: FakeReg())

    def test_scope_main_falls_back_to_worker(self, monkeypatch):
        from core.role_registry import AgentRole

        main_role = AgentRole(key="orchestrator", scope="main", prompt="main prompt")
        worker_role = AgentRole(key="worker", scope="any", prompt="worker prompt")
        self._fake_registry(monkeypatch, {"orchestrator": main_role, "worker": worker_role})
        sub = FakeSubagentAgent(tools=[_tool("shell")])
        returned = apply_subagent_role(sub, "orchestrator")
        assert sub.role == "worker"
        assert returned.scope != "main"

    def test_role_not_found_falls_back_to_worker(self, monkeypatch):
        from core.role_registry import AgentRole

        worker_role = AgentRole(key="worker", scope="any", prompt="worker prompt")
        self._fake_registry(monkeypatch, {"worker": worker_role})
        sub = FakeSubagentAgent(tools=[_tool("shell")])
        returned = apply_subagent_role(sub, "does_not_exist_xyz")
        assert hasattr(returned, "key")  # not None

    def test_tools_none_becomes_empty(self, monkeypatch):
        from core.role_registry import AgentRole

        worker_role = AgentRole(key="worker", scope="any", prompt="worker prompt")
        self._fake_registry(monkeypatch, {"worker": worker_role})
        sub = FakeSubagentAgent(tools=None)
        apply_subagent_role(sub, "worker")
        assert sub.tools == []

    def test_shell_description_overridden_others_preserved(self, monkeypatch):
        from core.role_registry import AgentRole

        worker_role = AgentRole(key="worker", scope="any", prompt="worker prompt")
        self._fake_registry(monkeypatch, {"worker": worker_role})
        sub = FakeSubagentAgent(tools=[_tool("shell"), _tool("read"), _tool("edit")])
        apply_subagent_role(sub, "worker")
        names = [t["function"]["name"] for t in sub.tools]
        assert names == ["shell", "read", "edit"]
        shell = next(t for t in sub.tools if t["function"]["name"] == "shell")
        assert "sync" in shell["function"]["description"].lower()
        read = next(t for t in sub.tools if t["function"]["name"] == "read")
        assert read["function"]["description"] == "desc read"

    def test_excluded_tools_removed(self, monkeypatch):
        from core.role_registry import AgentRole

        worker_role = AgentRole(key="worker", scope="any", prompt="worker prompt")
        self._fake_registry(monkeypatch, {"worker": worker_role})
        sub = FakeSubagentAgent(tools=[_tool("shell"), _tool("invoke_subagent"), _tool("ask_user")])
        apply_subagent_role(sub, "worker")
        names = [t["function"]["name"] for t in sub.tools]
        assert "invoke_subagent" not in names
        assert "ask_user" not in names
        assert "shell" in names


# ---------------------------------------------------------------------------
# cancel_running_subagents
# ---------------------------------------------------------------------------


class FakeCancelStore:
    def __init__(self, sessions=None):
        self.sessions = sessions or []
        self.saved = []

    def get_subagents_for_parent(self, parent_id):
        return [s for s in self.sessions if s.parent_id == parent_id]

    def list(self, kind=None):
        return list(self.sessions)

    def save(self, sess):
        self.saved.append(sess)


class FakeTask:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done

    def cancel(self):
        self.cancelled = True


class TestCancelRunning:
    def test_parent_id_none_lists_all_subagents(self):
        sess = make_session()
        store = FakeCancelStore(sessions=[sess])
        n = cancel_running_subagents(store)
        assert n == 1
        assert sess.status == STATUS_CANCELLED

    def test_done_task_not_cancelled_but_session_marked(self):
        sess = make_session()
        sess.async_task = FakeTask(done=True)
        store = FakeCancelStore(sessions=[sess])
        n = cancel_running_subagents(store)
        assert n == 1
        assert not hasattr(sess.async_task, "cancelled")
        assert sess.status == STATUS_CANCELLED

    def test_non_running_status_skipped(self):
        sess = make_session(status="completed")
        store = FakeCancelStore(sessions=[sess])
        n = cancel_running_subagents(store)
        assert n == 0
        assert sess.status == "completed"

    def test_async_task_none_skipped_cancel_but_marks(self):
        sess = make_session()
        sess.async_task = None
        store = FakeCancelStore(sessions=[sess])
        n = cancel_running_subagents(store)
        assert n == 1
        assert sess.status == STATUS_CANCELLED

    def test_returns_counter(self):
        a = make_session()
        b = make_session()
        a.async_task = FakeTask(done=False)
        b.async_task = FakeTask(done=False)
        store = FakeCancelStore(sessions=[a, b])
        n = cancel_running_subagents(store)
        assert n == 2
        assert a.async_task.cancelled
        assert b.async_task.cancelled
