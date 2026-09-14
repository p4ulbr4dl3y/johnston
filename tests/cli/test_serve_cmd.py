"""Integration tests for the ``johnston serve`` JSON-RPC daemon over stdio.

Spawns the daemon as an isolated subprocess (fake config dir, no provider/
API keys — no real LLM calls) and exercises the wire protocol documented in
``docs/jsonrpc_protocol.md``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from johnston.cli.entrypoint import build_parser

ROOT = Path(__file__).resolve().parents[2]


def _send(proc: subprocess.Popen, raw: str) -> list[dict]:
    """Write one or more raw lines to the daemon stdin and flush."""
    proc.stdin.write(raw)
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: float = 30.0, lines: int = 1) -> list[dict]:
    """Read ``lines`` JSON objects from the daemon stdout (blocking)."""
    out: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(out) < lines:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for daemon output")
        line = proc.stdout.readline()
        if not line:
            raise EOFError("Daemon stdout closed unexpectedly")
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _request(proc: subprocess.Popen, method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    """Send a single request and read its response line."""
    payload: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    _send(proc, json.dumps(payload) + "\n")
    (resp,) = _recv(proc, lines=1)
    return resp


def _request_till_response(
    proc: subprocess.Popen, method: str, params: dict | None = None, msg_id: int = 1, timeout: float = 30.0
) -> tuple[list[dict], dict]:
    """Send a request and read lines until the response carrying ``msg_id``.

    Returns ``(interleaved_messages, response)``. Streaming methods emit
    ``event`` notifications before their terminal response (§2.6).
    """
    payload: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    _send(proc, json.dumps(payload) + "\n")

    messages: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for daemon response")
        line = proc.stdout.readline()
        if not line:
            raise EOFError("Daemon stdout closed unexpectedly")
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("id") == msg_id and ("result" in msg or "error" in msg):
            return messages, msg
        messages.append(msg)


@pytest.fixture
def serve_proc(tmp_path):
    """Spawn a daemon subprocess with an isolated config dir."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # Provide no provider model in config: the daemon stays functional for
    # information/state methods and reports LLM errors without API keys.
    (cfg_dir / "config.json").write_text(
        json.dumps({"model": "fake-provider/fake-model"}),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["JOHNSTON_CONFIG_DIR"] = str(cfg_dir)
    env.pop("PYTEST_CURRENT_TEST", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "johnston", "serve", "--no-sandbox"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        env=env,
    )
    try:
        # Wait for the daemon to come up (first response to daemon.info
        # doubles as a readiness probe).
        resp = _request(proc, "daemon.info", msg_id=0)
        assert resp.get("result", {}).get("protocol_version") == "1.0"
        yield proc
    finally:
        try:
            _send(proc, '{"jsonrpc":"2.0","method":"daemon.shutdown"}\n')
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr, proc.stdin):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass


class TestServeParser:
    def test_parser_serve_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(
            ["serve", "--role", "worker", "--model", "gpt-4o", "--mode", "yolo", "--sandbox", "-w", "/tmp/ws"]
        )
        assert args.subcommand == "serve"
        assert args.role == "worker"
        assert args.model == "gpt-4o"
        assert args.mode == "yolo"
        assert args.sandbox is True
        assert args.workspace == ["/tmp/ws"]

    def test_parser_serve_no_sandbox(self):
        parser = build_parser()
        args = parser.parse_args(["serve", "--no-sandbox"])
        assert args.subcommand == "serve"
        assert args.no_sandbox is True


class TestServeDaemon:
    def test_daemon_info(self, serve_proc):
        resp = _request(serve_proc, "daemon.info", msg_id=1)
        result = resp.get("result")
        assert result is not None
        assert result["protocol_version"] == "1.0"
        assert result["implementation"] == "johnston-daemon"
        assert isinstance(result["pid"], int)
        assert isinstance(result["cwd"], str)

    def test_session_list_is_list(self, serve_proc):
        resp = _request(serve_proc, "session.list", msg_id=1)
        assert resp.get("result", {}).get("sessions") is not None
        assert isinstance(resp["result"]["sessions"], list)

    def test_unknown_method(self, serve_proc):
        resp = _request(serve_proc, "no.such.method", msg_id=1)
        assert resp.get("id") == 1
        err = resp.get("error")
        assert err is not None
        assert err["code"] == -32601
        assert err["data"]["kind"] == "method_not_found"
        assert err["data"]["method"] == "no.such.method"

    def test_parse_error_response(self, serve_proc):
        _send(serve_proc, '{"jsonrpc":"2.0","id":1,"method":broken}\n')
        (resp,) = _recv(serve_proc, lines=1)
        assert resp.get("id") is None
        assert resp.get("error", {}).get("code") == -32700

    def test_non_object_json_response(self, serve_proc):
        _send(serve_proc, "[1,2,3]\n")
        (resp,) = _recv(serve_proc, lines=1)
        assert resp.get("id") is None
        assert resp.get("error", {}).get("code") == -32600

    def test_notification_ignored(self, serve_proc):
        """Notifications carry no id and produce no response."""
        _send(serve_proc, '{"jsonrpc":"2.0","method":"some.notification"}\n')
        resp = _request(serve_proc, "daemon.info", msg_id=2)
        assert resp.get("id") == 2

    def test_prompt_stream_no_agent_error(self, serve_proc):
        """With no real provider configured, the stream fails via error event."""
        messages, resp = _request_till_response(
            serve_proc,
            "prompt.stream",
            {"prompt": "hello", "session_id": "s-unknown"},
            msg_id=1,
        )
        assert resp.get("id") == 1
        # The terminal error event precedes the response (fatal → no
        # turn_completed), which itself carries a flag-free result.
        event_types = [m.get("params", {}).get("type") for m in messages if m.get("method") == "event"]
        assert "error" in event_types
        # The RPC completes either with a summarized result or an error;
        # a real LLM call is never made (no provider configured).
        assert "result" in resp or "error" in resp

    def test_invalid_params_prompt_stream(self, serve_proc):
        resp = _request(serve_proc, "prompt.stream", {"prompt": ""}, msg_id=1)
        assert resp.get("error", {}).get("code") == -32602
        assert resp["error"]["data"]["kind"] == "invalid_params"

    def test_invalid_params_session_resume(self, serve_proc):
        resp = _request(serve_proc, "session.resume", {}, msg_id=1)
        assert resp.get("error", {}).get("code") == -32602
        assert resp["error"]["data"]["kind"] == "invalid_params"

    def test_session_resume_unknown_is_not_found(self, serve_proc):
        resp = _request(serve_proc, "session.resume", {"session_id": "s-does-not-exist"}, msg_id=1)
        assert resp.get("error", {}).get("code") == -32601
        assert resp["error"]["data"]["kind"] == "not_found"

    def test_config_get_unknown_key(self, serve_proc):
        resp = _request(serve_proc, "config.get", {"key": "no_such_key"}, msg_id=1)
        assert resp.get("error", {}).get("code") == -32601
        assert resp["error"]["data"]["kind"] == "not_found"

    def test_provider_list_is_list(self, serve_proc):
        resp = _request(serve_proc, "provider.list", msg_id=1)
        assert resp.get("result", {}).get("providers") is not None
        assert isinstance(resp["result"]["providers"], list)
