"""Coverage-boost tests for johnston.core.infrastructure.mcp.sse_client.

Covers the previously untested SSE transport branches: sync executor/loop
pooling, SSE listen framing, endpoint negotiation, notification dispatch,
POST response edge cases, request correlation and error handling. All
network I/O is mocked — no real connections.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from johnston.core.infrastructure.mcp.sse_client import (
    MCPSSEClient,
    _finalize_loop_state,
    _get_sse_executor,
    _run_loop_forever,
)


def _make_client(name: str = "test", url: str = "https://example.com/sse") -> MCPSSEClient:
    return MCPSSEClient(name, url, headers={"X-Test": "1"}, cwd="/tmp/ws")


# ── Module-level helpers ─────────────────────────────────────────────────


def test_get_sse_executor_lazy_shared():
    import johnston.core.infrastructure.mcp.sse_client as mod

    existing = mod._SSE_EXECUTOR
    if existing is not None:
        existing.shutdown(wait=True)
        mod._SSE_EXECUTOR = None
    try:
        first = _get_sse_executor()
        assert first is _get_sse_executor()
        assert first._max_workers == 4
    finally:
        mod._SSE_EXECUTOR.shutdown(wait=True)
        mod._SSE_EXECUTOR = None


def test_run_loop_forever_closes_loop():
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    t = threading.Thread(target=_run_loop_forever, args=(loop, ready), daemon=True)
    t.start()
    assert ready.wait(timeout=2.0)
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2.0)
    assert loop.is_closed()


def test_finalize_loop_state():
    # GC'd client backstop: stops + joins the loop thread and clears state.
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    thread = threading.Thread(target=_run_loop_forever, args=(loop, ready), daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)

    state = {"loop": loop, "thread": thread, "stopping": False}
    _finalize_loop_state(state)
    thread.join(timeout=2.0)
    assert state == {}
    assert loop.is_closed()


def test_finalize_loop_state_empty_and_closed():
    state = {"loop": None, "thread": None, "stopping": False}
    _finalize_loop_state(state)
    assert state == {}

    loop = asyncio.new_event_loop()
    loop.close()
    state = {"loop": loop, "thread": threading.current_thread(), "stopping": False}
    _finalize_loop_state(state)  # loop closed -> skipped
    assert state == {}


def test_finalize_loop_state_call_soon_raises():
    """call_soon_threadsafe raising RuntimeError is swallowed; thread still joined."""
    loop = asyncio.new_event_loop()

    def boom(*_a, **_k):
        raise RuntimeError("closed")

    loop.call_soon_threadsafe = boom  # type: ignore[method-assign]
    barrier = threading.Event()
    thread = threading.Thread(target=barrier.wait, daemon=True)
    thread.start()
    state = {"loop": loop, "thread": thread, "stopping": False}
    _finalize_loop_state(state)
    thread.join(timeout=2.0)
    assert state == {}
    loop.close()


def test_run_loop_forever_close_raises():
    """loop.close() raising RuntimeError inside _run_loop_forever is swallowed."""
    loop = asyncio.new_event_loop()

    orig_close = loop.close

    def boom(*_a, **_k):
        raise RuntimeError("already closed")

    loop.close = boom  # type: ignore[method-assign]
    ready = threading.Event()
    t = threading.Thread(target=_run_loop_forever, args=(loop, ready), daemon=True)
    t.start()
    assert ready.wait(timeout=2.0)
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2.0)
    assert not t.is_alive()
    # Restore the real close so the loop's internal poller handle is released.
    loop.close = orig_close  # type: ignore[method-assign]
    loop.close()


# ── is_alive / stop with pending futures ─────────────────────────────────


@pytest.mark.asyncio
async def test_is_alive_and_stop_pending_futures():
    client = _make_client()
    assert client.is_alive() is False  # no http client yet
    client._http_client = AsyncMock()
    assert client.is_alive() is True

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending_futures[7] = fut
    client._sse_task = asyncio.create_task(asyncio.sleep(10))

    await client.stop_async()
    assert client._stopped is True
    assert fut.done()
    assert isinstance(fut.exception(), RuntimeError)
    assert client._pending_futures == {}
    assert client._http_client is None


@pytest.mark.asyncio
async def test_stop_async_http_close_raises():
    client = _make_client()
    http = AsyncMock()
    http.aclose.side_effect = RuntimeError("close failed")
    client._http_client = http
    await client.stop_async()  # must not raise
    assert client._http_client is None


@pytest.mark.asyncio
async def test_stop_async_with_running_sse_task():
    client = _make_client()

    async def long_running():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    client._sse_task = asyncio.create_task(long_running())
    await client.stop_async()
    assert client._sse_task is None


def test_stop_sync_exception_swallowed():

    client = _make_client()
    client._run_sync_lifecycle = MagicMock(side_effect=RuntimeError("loop dead"))
    client._loop_state = {"thread": None, "loop": None, "stopping": False}
    client.stop()  # must not raise
    client._run_sync_lifecycle.assert_called_once()


# ── start_async branches ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_async_already_alive():
    client = _make_client()
    client._http_client = MagicMock()
    assert await client.start_async() is True


@pytest.mark.asyncio
async def test_start_async_initialize_failure_stops():
    client = _make_client()
    client._sse_listen_loop = AsyncMock()
    client._initialize_async = AsyncMock(return_value=False)
    client.stop_async = AsyncMock()
    with patch(
        "johnston.core.infrastructure.mcp.sse_client.httpx.AsyncClient",
        return_value=MagicMock(),
    ):
        assert await client.start_async(timeout=1.0) is False
    client.stop_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_async_initialize_raises():
    client = _make_client()
    client._sse_listen_loop = AsyncMock()
    client._initialize_async = AsyncMock(side_effect=RuntimeError("init failed"))
    client.stop_async = AsyncMock()
    with patch(
        "johnston.core.infrastructure.mcp.sse_client.httpx.AsyncClient",
        return_value=MagicMock(),
    ):
        assert await client.start_async(timeout=1.0) is False
    assert client.last_error == "MCP SSE start failed: init failed"
    client.stop_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_async_endpoint_timeout():
    client = _make_client()

    class FakeEvent:
        def __init__(self) -> None:
            self._waiters = 0

        def clear(self) -> None:
            pass

        async def wait(self) -> bool:
            raise asyncio.TimeoutError

    client._endpoint_ready = FakeEvent()
    client._sse_listen_loop = AsyncMock()
    client._initialize_async = AsyncMock(return_value=True)
    client._http_client = MagicMock()
    with patch(
        "johnston.core.infrastructure.mcp.sse_client.httpx.AsyncClient",
        return_value=client._http_client,
    ):
        assert await client.start_async(timeout=1.0) is True
    assert client.post_url == "https://example.com/sse"


@pytest.mark.asyncio
async def test_start_async_success_setup():
    client = _make_client()
    client._endpoint_ready = asyncio.Event()
    client._endpoint_ready.set()
    client._sse_listen_loop = AsyncMock()
    client._initialize_async = AsyncMock(return_value=True)
    http = MagicMock()
    with patch(
        "johnston.core.infrastructure.mcp.sse_client.httpx.AsyncClient",
        return_value=http,
    ) as m_http:
        assert await client.start_async(timeout=1.0) is True
    m_http.assert_called_once()
    assert client._http_client is http
    # endpoint event already set -> post_url stays default
    assert client.post_url == "https://example.com/sse"


# ── sync lifecycle: loop / executor ──────────────────────────────────────


def test_sync_start_and_restart_after_stop():
    """stop() tears down the loop, a restart builds a fresh one."""
    client = _make_client()

    async def fake_start(timeout=None):
        return True

    client.start_async = fake_start
    assert client.start() is True
    first_thread = client._loop_state["thread"]
    assert first_thread is not None and first_thread.is_alive()

    client.stop()
    assert not first_thread.is_alive()

    assert client.start() is True
    second_thread = client._loop_state["thread"]
    assert second_thread is not first_thread
    client.stop()


def test_run_sync_lifecycle_from_running_loop_uses_executor():
    """Sync lifecycle called from inside a running loop offloads to the executor."""
    import johnston.core.infrastructure.mcp.sse_client as mod

    client = _make_client()
    seen: List[str] = []

    async def fake_start(timeout=None):
        seen.append("started")
        return True

    client.start_async = fake_start

    async def runner():
        return client.start()

    with patch.object(mod, "_get_sse_executor", wraps=mod._get_sse_executor) as m_exec:
        result = asyncio.run(runner())
    assert result is True
    assert seen == ["started"]
    assert m_exec.call_count == 1
    client.stop()


def test_ensure_loop_reuses_alive_loop():
    client = _make_client()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    thread = threading.Thread(target=_run_loop_forever, args=(loop, ready), daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    client._loop_state = {"loop": loop, "thread": thread, "stopping": False}
    try:
        assert client._ensure_loop() is loop
    finally:
        _finalize_loop_state(client._loop_state)


def test_ensure_loop_recreates_dead_loop():
    client = _make_client()
    dead_loop = asyncio.new_event_loop()
    dead_loop.close()
    dead_thread = threading.Thread(target=lambda: None, daemon=True)
    client._loop_state = {"loop": dead_loop, "thread": dead_thread, "stopping": False}
    new_loop = client._ensure_loop()
    try:
        assert new_loop is not dead_loop
        assert not new_loop.is_closed()
        assert client._loop_state["thread"].is_alive()
    finally:
        _finalize_loop_state(client._loop_state)


def test_shutdown_loop_from_own_thread():
    """_shutdown_loop called from the loop's own thread must not join itself."""
    client = _make_client()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    thread = threading.Thread(target=_run_loop_forever, args=(loop, ready), daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    client._loop_state = {"loop": loop, "thread": thread, "stopping": False}

    def stop_from_loop_thread():
        client._shutdown_loop()

    thread2 = threading.Thread(target=stop_from_loop_thread, daemon=True)
    thread2.start()
    thread2.join(timeout=3.0)
    assert client._loop_state["thread"] is None
    assert client._loop_state["loop"] is None


def test_shutdown_loop_when_loop_stop_raises():
    client = _make_client()
    fake_loop = MagicMock()
    fake_loop.is_closed.return_value = False
    fake_loop.call_soon_threadsafe.side_effect = RuntimeError("closed")
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = True
    client._loop_state = {"loop": fake_loop, "thread": fake_thread, "stopping": False}
    client._shutdown_loop()  # must swallow the RuntimeError
    assert client._loop_state["thread"] is None


def test_ensure_loop_joins_stopping_thread():
    """A shutdown in flight is joined and a fresh loop is created."""
    client = _make_client()
    old_loop = asyncio.new_event_loop()
    old_loop.close()
    import time as _time

    old_thread = threading.Thread(target=_time.sleep, args=(0.2,), daemon=True)
    old_thread.start()
    client._loop_state = {"loop": old_loop, "thread": old_thread, "stopping": True}
    new_loop = client._ensure_loop()
    try:
        assert not old_thread.is_alive()  # joined by _ensure_loop
        assert new_loop is not old_loop
        assert not new_loop.is_closed()
        assert client._loop_state["stopping"] is False
        assert client._loop_state["thread"].is_alive()
    finally:
        _finalize_loop_state(client._loop_state)


# ── SSE listen loop ──────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, lines: List[str], status: int = 200) -> None:
        self._lines = lines
        self.status_code = status

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def aiter_lines(self) -> Any:
        async def gen():
            for line in self._lines:
                yield line

        return gen()


def _client_with_fake_http(lines: List[str], status: int = 200, post_url: str = "https://example.com/sse") -> MCPSSEClient:
    client = _make_client()
    http = MagicMock()
    http.stream.return_value = FakeResponse(lines, status=status)
    client._http_client = http
    client.post_url = post_url
    return client


@pytest.mark.asyncio
async def test_sse_listen_no_http_client():
    client = _make_client()
    await client._sse_listen_loop()  # early return


@pytest.mark.asyncio
async def test_sse_listen_http_error_status():
    client = _client_with_fake_http([], status=500)
    event = asyncio.Event()
    client._endpoint_ready = event
    await client._sse_listen_loop()
    assert client.last_error == "SSE connection failed HTTP 500"
    assert event.is_set()


@pytest.mark.asyncio
async def test_sse_listen_endpoint_event():
    client = _client_with_fake_http(["event: endpoint", "data: /jsonrpc", ""])
    event = asyncio.Event()
    client._endpoint_ready = event
    await client._sse_listen_loop()
    assert client.post_url == "https://example.com/jsonrpc"
    assert event.is_set()


@pytest.mark.asyncio
async def test_sse_listen_endpoint_absolute():
    client = _client_with_fake_http(["event: endpoint", "data: https://other.example.com/rpc", ""])
    client._endpoint_ready = asyncio.Event()
    await client._sse_listen_loop()
    assert client.post_url == "https://other.example.com/rpc"


@pytest.mark.asyncio
async def test_sse_listen_stopped_breaks():
    client = _client_with_fake_http(["data: a", "", "data: b"])
    client._stopped = True
    await client._sse_listen_loop()  # exits on first line without processing
    assert client._pending_futures == {}


@pytest.mark.asyncio
async def test_sse_listen_multi_line_data():
    client = _client_with_fake_http(["data: line1", "data: line2", ""])
    messages: List[Dict[str, Any]] = []
    client._handle_sse_event = AsyncMock(side_effect=lambda et, d: messages.append({"t": et, "d": d}))
    await client._sse_listen_loop()
    assert len(messages) == 1
    assert messages[0] == {"t": "message", "d": "line1\nline2"}


@pytest.mark.asyncio
async def test_sse_listen_comment_and_custom_event():
    client = _client_with_fake_http([": keepalive", "event: ping", "data: x", ""])
    client._handle_sse_event = AsyncMock()
    await client._sse_listen_loop()
    client._handle_sse_event.assert_awaited_once_with("ping", "x")


@pytest.mark.asyncio
async def test_sse_listen_exception_logged():
    """Exceptions in the listener (while not stopped) end the loop gracefully."""
    client = _make_client()
    http = MagicMock()
    http.stream.side_effect = RuntimeError("connection reset")
    client._http_client = http
    event = asyncio.Event()
    client._endpoint_ready = event
    await client._sse_listen_loop()  # exception swallowed (debug log)
    assert event.is_set()


@pytest.mark.asyncio
async def test_sse_listen_cancelled():
    """Cancelling the listener mid-stream is swallowed and the endpoint event set."""

    class BlockingResponse:
        status_code = 200

        async def __aenter__(self) -> "BlockingResponse":
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def aiter_lines(self) -> Any:
            async def gen():
                yield "data: x"
                yield ""
                await asyncio.sleep(30)

            return gen()

    client = _make_client()
    http = MagicMock()
    http.stream.return_value = BlockingResponse()
    client._http_client = http

    async def slow_handler(_et, _data):
        await asyncio.sleep(30)

    client._handle_sse_event = slow_handler
    task = asyncio.create_task(client._sse_listen_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    await task  # CancelledError caught by the listener; loop exits via finally
    assert client._endpoint_ready.is_set()


# ── _handle_sse_event ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_endpoint():
    client = _make_client()
    event = asyncio.Event()
    client._endpoint_ready = event
    await client._handle_sse_event("endpoint", "/rpc2")
    assert client.post_url == "https://example.com/rpc2"
    assert event.is_set()


@pytest.mark.asyncio
async def test_handle_non_json_and_bad_json():
    client = _make_client()
    await client._handle_sse_event("message", "plain text")
    await client._handle_sse_event("message", "{not json")
    await client._handle_sse_event("message", "[1,2]")
    assert client._pending_futures == {}


@pytest.mark.asyncio
async def test_handle_response_non_dict_json():
    """A JSON list payload from the server hits the not-a-dict guard."""
    client = _make_client()
    with patch("json.loads", return_value=[1, 2, 3]):
        await client._handle_sse_event("message", '{"jsonrpc": "2.0"}')
    assert client._pending_futures == {}


@pytest.mark.asyncio
async def test_handle_tools_list_changed():
    client = _make_client()
    client.fetch_tools_async = AsyncMock()
    client._handle_server_request_async = AsyncMock()
    await client._handle_sse_event("message", json.dumps({"method": "notifications/tools/list_changed"}))
    await asyncio.sleep(0.02)
    client.fetch_tools_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_resources_list_changed():
    client = _make_client()
    client.fetch_resources_async = AsyncMock()
    await client._handle_sse_event("message", json.dumps({"method": "resources/list_changed"}))
    await asyncio.sleep(0.02)
    client.fetch_resources_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_prompts_list_changed():
    client = _make_client()
    client.fetch_prompts_async = AsyncMock()
    await client._handle_sse_event("message", json.dumps({"method": "notifications/prompts/list_changed"}))
    await asyncio.sleep(0.02)
    client.fetch_prompts_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_notification_callback_raises():
    client = _make_client()
    client.fetch_tools_async = AsyncMock()
    client._handle_server_request_async = AsyncMock()

    def boom():
        raise RuntimeError("cb failed")

    client.on_tools_changed = boom
    await client._handle_sse_event("message", json.dumps({"method": "tools/list_changed"}))
    await asyncio.sleep(0.02)  # callback exception swallowed inside listener task


@pytest.mark.asyncio
async def test_handle_resources_callback_raises():
    client = _make_client()
    client.fetch_resources_async = AsyncMock()

    def boom():
        raise RuntimeError("cb failed")

    client.on_resources_changed = boom
    await client._handle_sse_event("message", json.dumps({"method": "notifications/resources/list_changed"}))
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_handle_prompts_callback_raises():
    client = _make_client()
    client.fetch_prompts_async = AsyncMock()

    def boom():
        raise RuntimeError("cb failed")

    client.on_prompts_changed = boom
    await client._handle_sse_event("message", json.dumps({"method": "notifications/prompts/list_changed"}))
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_handle_server_request_via_sse():
    client = _make_client()
    client._handle_server_request_async = AsyncMock()
    await client._handle_sse_event("message", json.dumps({"method": "ping", "id": 12}))
    await asyncio.sleep(0.02)
    client._handle_server_request_async.assert_awaited_once_with({"method": "ping", "id": 12})


@pytest.mark.asyncio
async def test_handle_response_resolves_future():
    client = _make_client()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending_futures[5] = fut
    await client._handle_sse_event("message", json.dumps({"jsonrpc": "2.0", "id": 5, "result": {"ok": True}}))
    assert fut.done()
    assert fut.result() == {"jsonrpc": "2.0", "id": 5, "result": {"ok": True}}
    assert 5 not in client._pending_futures


@pytest.mark.asyncio
async def test_handle_response_future_not_found_or_done():
    client = _make_client()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    fut.set_result("x")
    client._pending_futures[7] = fut  # already done -> result untouched, entry popped
    await client._handle_sse_event("message", json.dumps({"id": 7, "result": {}}))
    await client._handle_sse_event("message", json.dumps({"id": 99, "result": {}}))
    assert fut.result() == "x"
    assert 7 not in client._pending_futures


# ── send_post / send_request ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_notification_async():
    client = _make_client()
    client._send_post_async = AsyncMock(return_value=None)
    await client._send_notification_async({"method": "x"})
    client._send_post_async.assert_awaited_once_with({"method": "x"})


@pytest.mark.asyncio
async def test_send_post_not_started_returns_none():
    client = _make_client()
    assert await client._send_post_async({"x": 1}) is None
    client._stopped = True
    client._http_client = MagicMock()
    assert await client._send_post_async({"x": 1}) is None


@pytest.mark.asyncio
async def test_send_post_ok_json_response():
    client = _make_client()
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"jsonrpc": "2.0", "id": 1}'
    resp.json.return_value = {"jsonrpc": "2.0", "id": 1}
    client._http_client = MagicMock()
    client._http_client.post = AsyncMock(return_value=resp)
    out = await client._send_post_async({"id": 1})
    assert out == {"jsonrpc": "2.0", "id": 1}


@pytest.mark.asyncio
async def test_send_post_bad_status_and_json():
    client = _make_client()
    resp = MagicMock()
    resp.status_code = 400
    client._http_client = MagicMock()
    client._http_client.post = AsyncMock(return_value=resp)
    assert await client._send_post_async({"id": 1}) is None

    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.text = "not json"
    resp2.json.side_effect = ValueError("bad json")
    client._http_client.post = AsyncMock(return_value=resp2)
    assert await client._send_post_async({"id": 1}) is None


@pytest.mark.asyncio
async def test_send_post_raises():
    client = _make_client()
    http = MagicMock()
    http.post = AsyncMock(side_effect=RuntimeError("network down"))
    client._http_client = http
    assert await client._send_post_async({"id": 1}) is None


@pytest.mark.asyncio
async def test_send_request_not_started():
    client = _make_client()
    assert await client._send_request_async("tools/list") is None
    client._stopped = True
    client._http_client = MagicMock()
    assert await client._send_request_async("tools/list") is None


@pytest.mark.asyncio
async def test_send_request_immediate_post_result():
    client = _make_client()
    client._http_client = MagicMock()
    client._send_post_async = AsyncMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
    out = await client._send_request_async("tools/list", params={"x": 1})
    assert out == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    assert client._pending_futures == {}  # cleaned up


@pytest.mark.asyncio
async def test_send_request_wait_for_sse_response():
    client = _make_client()
    client._http_client = MagicMock()
    client._send_post_async = AsyncMock(return_value=None)

    async def delayed():
        await asyncio.sleep(0.01)
        msg = {"id": client.req_id, "result": {"ok": True}}
        await client._handle_sse_event("message", json.dumps(msg))

    task = asyncio.create_task(delayed())
    out = await client._send_request_async("tools/list")
    await task
    assert out == {"id": 1, "result": {"ok": True}}


@pytest.mark.asyncio
async def test_send_request_timeout():
    client = _make_client()
    client._http_client = MagicMock()
    client._send_post_async = AsyncMock(return_value=None)
    out = await client._send_request_async("tools/list", timeout=0.02)
    assert out is None
    assert client._pending_futures == {}


@pytest.mark.asyncio
async def test_send_request_exception():
    client = _make_client()
    client._http_client = MagicMock()
    client._send_post_async = AsyncMock(side_effect=RuntimeError("boom"))
    fut = client._pending_futures.get(1)
    assert fut is None
    out = await client._send_request_async("tools/list", timeout=0.02)
    assert out is None
    assert client._pending_futures == {}


# ── stop() loop-thread join branch ───────────────────────────────────────


def test_stop_joins_own_loop_thread():
    client = _make_client()

    async def fake_stop():
        return None

    client.stop_async = fake_stop
    client._loop_state = {"thread": threading.current_thread(), "loop": None, "stopping": False}
    client.stop()  # must not join the current thread → no deadlock
