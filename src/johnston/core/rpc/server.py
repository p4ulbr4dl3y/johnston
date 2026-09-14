"""JSON-RPC 2.0 server over stdio for Johnston daemon mode.

Reads line-delimited JSON from stdin, dispatches to JohnstonClient facade
methods, and writes responses/notifications to stdout.  Zero imports from
``johnston.tui``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from typing import Any

from johnston.core.rpc.codec import dto_to_dict, serialize_event

logger = logging.getLogger(__name__)

# ── Protocol constants ────────────────────────────────────────────────────

PROTOCOL_VERSION = "1.0"
IMPLEMENTATION = "johnston-daemon"

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TURN_IN_PROGRESS = -32001


# ── Stream event type names (wire names per protocol spec §4.1) ───────────

def _build_event_type_names() -> dict[type, str]:
    from johnston.core.dto import (
        CompactionEventDTO,
        ContentDeltaDTO,
        ErrorEventDTO,
        QueuedUserMessageDTO,
        RetryEventDTO,
        ThinkingDeltaDTO,
        ToolCallDTO,
        ToolResultDTO,
        TurnCompletedDTO,
    )

    return {
        ContentDeltaDTO: "content_delta",
        ThinkingDeltaDTO: "thinking_delta",
        ToolCallDTO: "tool_call",
        ToolResultDTO: "tool_result",
        CompactionEventDTO: "compaction",
        TurnCompletedDTO: "turn_completed",
        ErrorEventDTO: "error",
        QueuedUserMessageDTO: "queued_user_message",
        RetryEventDTO: "retry",
    }


_EVENT_TYPE_NAMES: dict[type, str] | None = None


def _event_type_name(event: Any) -> str:
    global _EVENT_TYPE_NAMES
    if _EVENT_TYPE_NAMES is None:
        _EVENT_TYPE_NAMES = _build_event_type_names()
    return _EVENT_TYPE_NAMES.get(type(event), type(event).__name__)


# ── Structured RPC error ──────────────────────────────────────────────────


def _risk_level(tool_name: str, args: dict[str, Any]) -> str:
    """Best-effort risk estimate for a permission_request notification."""
    name = (tool_name or "").strip().lower()
    if name in ("shell", "bash"):
        cmd = args.get("command") if isinstance(args, dict) else None
        if isinstance(cmd, str) and any(
            kw in cmd.lower()
            for kw in ("rm ", "rm -", "dd ", "mkfs", "shutdown", "reboot", "kill -9", "git push --force", "sudo ")
        ):
            return "high"
        return "medium"
    if name in ("create", "edit", "write", "delete", "remove", "kill", "invoke_subagent"):
        return "medium"
    return "low"


def _strip_type(value: Any) -> Any:
    """Recursively drop codec ``_type`` discriminators from method results.

    Result shapes must match the protocol spec (JSON field names are exactly
    the DTO dataclass field names); the codec's ``_type`` key is transport
    metadata. Event notifications keep ``serialize_event`` output verbatim.
    """
    if isinstance(value, dict):
        return {k: _strip_type(v) for k, v in value.items() if k != "_type"}
    if isinstance(value, list):
        return [_strip_type(v) for v in value]
    return value


class RpcError(Exception):
    """Structured JSON-RPC error with code, message, and optional data."""

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.data = data or {}
        super().__init__(message)


# ── Sentinel for missing config keys ──────────────────────────────────────

_MISSING = object()


# ── Daemon host (Headless HostProtocol for JSON-RPC mode) ─────────────────


class DaemonHost:
    """Headless host implementing the HostProtocol for daemon mode.

    Bridges tool permission prompts (``confirm_permission``, ``ask_user``)
    into JSON-RPC ``event`` notifications and suspends the turn while
    awaiting an ``interaction.resolve`` request from the client.
    """

    def __init__(
        self,
        write_msg: Any,
        pending: dict[str, asyncio.Future[Any]],
        *,
        project_dir: str = "",
    ) -> None:
        self._write_msg = write_msg
        self._pending = pending
        self.project_dir: str = project_dir or os.getcwd()
        self.current_session_id: str | None = None
        self.task_manager: Any = None
        self.pm: Any = None
        self.sandbox_enabled: bool = False
        self.is_read_only: bool = False
        self.session: Any = None
        self.message_queue: list[Any] = []
        self._fg_tasks: dict[str, Any] = {}

    # ── HostProtocol: interaction ──────────────────────────────────────────

    async def confirm_permission(
        self,
        tool_name: str,
        args: dict[str, Any],
        reason: str = "",
        perm_name: str | None = None,
        *call_args: Any,
        **kwargs: Any,
    ) -> bool:
        token = f"perm-{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        self._pending[token] = fut
        try:
            await self._write_msg(
                {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {
                        "type": "permission_request",
                        "data": {
                            "tool_name": tool_name,
                            "args": args,
                            "risk_level": _risk_level(tool_name, args),
                            "reason": reason or "",
                            "id": token,
                        },
                    },
                }
            )
            result = await fut
            return bool(result)
        finally:
            self._pending.pop(token, None)

    async def ask_user(self, questions: list[dict[str, Any]]) -> str:
        token = f"ask-{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[token] = fut
        try:
            await self._write_msg(
                {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {
                        "type": "ask_user",
                        "data": {"questions": questions, "id": token},
                    },
                }
            )
            result = await fut
            return str(result or "")
        finally:
            self._pending.pop(token, None)

    # ── HostProtocol: stubs (no-op in headless mode) ──────────────────────

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False) -> None:
        pass

    def refresh_status_footer(self) -> None:
        pass

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        pass

    def on_plan_update(self, plan: list[Any], status: str = "", *args: Any, **kwargs: Any) -> None:
        pass

    def attach_shell_widget(
        self,
        task_id: str,
        widget: Any,
        log_path: str | None = None,
        is_background: bool = False,
    ) -> None:
        pass

    def detach_shell_widget(self, task_id: str) -> None:
        pass

    def register_foreground_shell_task(self, task_id: str, task: Any) -> None:
        self._fg_tasks[task_id] = task

    def cleanup_foreground_shell_task(self, task_id: str) -> None:
        self._fg_tasks.pop(task_id, None)

    def get_foreground_shell_task(self, task_id: str) -> Any | None:
        return self._fg_tasks.get(task_id)

    def terminate_task_widget(
        self,
        task_id: str,
        output: str = "[killed]",
        status: str = "done",
    ) -> None:
        self._fg_tasks.pop(task_id, None)


# ── Config key helpers ────────────────────────────────────────────────────


def _get_config_value(key: str, client: Any, host: DaemonHost) -> Any:
    """Resolve a daemon config key to its current value."""
    if key == "sandbox_enabled":
        return bool(client.sandbox)
    if key == "thinking_effort":
        return client.get_thinking_effort() if hasattr(client, "get_thinking_effort") else ""
    if key == "provider":
        return getattr(client, "provider", "")
    if key == "model":
        return getattr(client, "model", "")
    if key == "cwd":
        return os.getcwd()
    if key == "pid":
        return os.getpid()
    return _MISSING


def _set_config_value(key: str, value: Any, client: Any, host: DaemonHost) -> None:
    """Apply a daemon config change."""
    if key == "sandbox_enabled":
        client.sandbox = bool(value)
        if client.agent is not None:
            client.agent.sandbox_enabled = bool(value)
        host.sandbox_enabled = bool(value)
    elif key == "thinking_effort":
        if hasattr(client, "set_thinking_effort"):
            client.set_thinking_effort(str(value))
    else:
        raise RpcError(METHOD_NOT_FOUND, f"Cannot set config key: {key}", {"kind": "not_found"})


# ── Server loop ───────────────────────────────────────────────────────────


async def _serve(
    client: Any,
    *,
    stdin: Any = None,
    stdout: Any = None,
    _reader: asyncio.StreamReader | None = None,
) -> int:
    """Run the JSON-RPC stdio server loop.

    Parameters
    ----------
    client:
        A fully-initialised ``JohnstonClient`` instance.
    stdin / stdout:
        File objects for I/O (default ``sys.stdin`` / ``sys.stdout``).
    _reader:
        Optional pre-built ``StreamReader`` for testing (bypasses pipe setup).

    Returns
    -------
    int
        Exit code (0 on clean shutdown).
    """
    from johnston.core.dto import TurnCompletedDTO

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    write_lock = asyncio.Lock()
    pending: dict[str, asyncio.Future[Any]] = {}
    active_turns: set[str] = set()
    shutting_down = False
    request_tasks: set[asyncio.Task] = set()

    # ── Stdin reader setup ─────────────────────────────────────────────
    transport = None
    if _reader is not None:
        stream_reader = _reader
    else:
        stream_reader = asyncio.StreamReader()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(stream_reader),
            stdin,
        )

    # ── Write helper ───────────────────────────────────────────────────
    async def write_msg(msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False, default=str) + "\n"
        async with write_lock:
            try:
                stdout.write(line)
                stdout.flush()
            except Exception:
                logger.debug("Failed to write to stdout", exc_info=True)

    # ── Daemon host ────────────────────────────────────────────────────
    host = DaemonHost(write_msg, pending, project_dir=os.getcwd())
    if getattr(client, "agent", None) is not None:
        client.agent.app = host

    # ── Interaction resolver ───────────────────────────────────────────
    async def resolve_interaction(params: dict[str, Any]) -> None:
        token = params.get("id", "")
        if not token:
            return
        fut = pending.get(token)
        if fut is None or fut.done():
            return
        if "allowed" in params:
            fut.set_result(params["allowed"])
        elif "answer" in params:
            fut.set_result(params["answer"])
        else:
            fut.set_result(None)

    # ── Request dispatcher ─────────────────────────────────────────────
    async def handle_request(method: str, msg_id: Any, params: dict[str, Any]) -> None:
        try:
            handler = _METHODS.get(method)
            if handler is None:
                raise RpcError(
                    METHOD_NOT_FOUND,
                    f"Method not found: {method}",
                    {"kind": "method_not_found", "method": method},
                )
            result = await handler(params)
            await write_msg({"jsonrpc": "2.0", "id": msg_id, "result": result})
        except RpcError as exc:
            await write_msg(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": exc.code, "message": exc.message, "data": exc.data},
                }
            )
        except Exception as exc:
            logger.debug("Unhandled error in %s: %s", method, exc, exc_info=True)
            await write_msg(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": INTERNAL_ERROR,
                        "message": str(exc),
                        "data": {"kind": "internal_error"},
                    },
                }
            )

    # ── Method handlers ────────────────────────────────────────────────

    async def _h_daemon_info(_p: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "implementation": IMPLEMENTATION,
            "pid": os.getpid(),
            "cwd": os.getcwd(),
        }

    async def _h_daemon_shutdown(_p: dict[str, Any]) -> None:
        nonlocal shutting_down
        shutting_down = True

    async def _h_session_list(_p: dict[str, Any]) -> dict[str, Any]:
        sessions = client.get_sessions()
        return {"sessions": [dto_to_dict(s) for s in sessions]}

    async def _h_session_create(p: dict[str, Any]) -> dict[str, Any]:
        title = p.get("title", "")
        role = p.get("role", "worker")
        if client.store is not None and hasattr(client.store, "create_main"):
            sess = client.store.create_main(role=role)
        else:
            raise RpcError(INTERNAL_ERROR, "Session store unavailable", {"kind": "manager"})
        if title:
            sess._title = title  # type: ignore[attr-defined]
            sess.touch()
            if client.store is not None and hasattr(client.store, "save"):
                client.store.save(sess)
        client.session = sess
        client.session_id = str(sess.id)
        host.current_session_id = client.session_id
        session_dto = client.get_session(str(sess.id))
        return {"session": dto_to_dict(session_dto) if session_dto else {}}

    async def _h_session_resume(p: dict[str, Any]) -> dict[str, Any]:
        sid = p.get("session_id", "")
        if not sid:
            raise RpcError(INVALID_PARAMS, "session_id required", {"kind": "invalid_params"})
        session_dto = client.get_session(sid)
        if session_dto is None:
            raise RpcError(METHOD_NOT_FOUND, f"Session not found: {sid}", {"kind": "not_found"})
        client.session_id = sid
        host.current_session_id = sid
        return {"session": dto_to_dict(session_dto)}

    async def _h_session_delete(p: dict[str, Any]) -> dict[str, Any]:
        sid = p.get("session_id", "")
        if not sid:
            raise RpcError(INVALID_PARAMS, "session_id required", {"kind": "invalid_params"})
        if client.store is not None and hasattr(client.store, "delete"):
            client.store.delete(sid)
        return {"deleted": True}

    async def _h_session_export(_p: dict[str, Any]) -> dict[str, Any]:
        raise RpcError(
            METHOD_NOT_FOUND,
            "session.export not yet implemented",
            {"kind": "method_not_found", "method": "session.export"},
        )

    async def _h_prompt_stream(p: dict[str, Any]) -> dict[str, Any]:
        prompt_text = p.get("prompt", "")
        if not prompt_text:
            raise RpcError(INVALID_PARAMS, "prompt required", {"kind": "invalid_params"})
        sid = p.get("session_id") or client.session_id
        if sid in active_turns:
            raise RpcError(TURN_IN_PROGRESS, "Turn in progress", {"kind": "turn_in_progress", "session_id": sid})
        active_turns.add(sid)
        try:
            return await _do_stream(prompt_text, p.get("attachments"), sid)
        finally:
            active_turns.discard(sid)

    async def _do_stream(prompt_text: str, attachments: list[Any] | None, sid: str) -> dict[str, Any]:
        turn_completed: TurnCompletedDTO | None = None
        async for event in client.stream(prompt_text, attachments=attachments):
            await write_msg(
                {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {"type": _event_type_name(event), "data": serialize_event(event)},
                }
            )
            if isinstance(event, TurnCompletedDTO):
                turn_completed = event

        if turn_completed is None:
            turn_completed = TurnCompletedDTO()
        result = _strip_type(dto_to_dict(turn_completed))
        result["session_id"] = sid
        return result

    async def _h_prompt(p: dict[str, Any]) -> dict[str, Any]:
        prompt_text = p.get("prompt", "")
        if not prompt_text:
            raise RpcError(INVALID_PARAMS, "prompt required", {"kind": "invalid_params"})
        sid = p.get("session_id") or client.session_id
        if sid in active_turns:
            raise RpcError(TURN_IN_PROGRESS, "Turn in progress", {"kind": "turn_in_progress", "session_id": sid})
        active_turns.add(sid)
        try:
            completed = await client.prompt(prompt_text, attachments=p.get("attachments"))
            result = dto_to_dict(completed)
            result["session_id"] = sid
            return result
        finally:
            active_turns.discard(sid)

    async def _h_compact(p: dict[str, Any]) -> dict[str, Any]:
        sid = p.get("session_id") or client.session_id
        if sid in active_turns:
            raise RpcError(TURN_IN_PROGRESS, "Turn in progress", {"kind": "turn_in_progress", "session_id": sid})
        result = await client.compact()
        return dto_to_dict(result)

    async def _h_rewind_points(p: dict[str, Any]) -> dict[str, Any]:
        sid = p.get("session_id") or client.session_id
        if sid in active_turns:
            raise RpcError(TURN_IN_PROGRESS, "Turn in progress", {"kind": "turn_in_progress", "session_id": sid})
        points = await client.get_rewind_points()
        return {"points": [dto_to_dict(pt) for pt in points]}

    async def _h_provider_list(_p: dict[str, Any]) -> dict[str, Any]:
        providers = client.get_providers()
        return {"providers": [dto_to_dict(p) for p in providers]}

    async def _h_model_info(p: dict[str, Any]) -> dict[str, Any]:
        pk = p.get("provider_key", "")
        mn = p.get("model_name", "")
        if not pk or not mn:
            raise RpcError(INVALID_PARAMS, "provider_key and model_name required", {"kind": "invalid_params"})
        return dto_to_dict(client.get_model_info(pk, mn))

    async def _h_model_estimate_cost(p: dict[str, Any]) -> dict[str, Any]:
        pk = p.get("provider_key", "")
        mn = p.get("model_name", "")
        tt = int(p.get("total_tokens", 0))
        cost = client.estimate_cost(pk, mn, tt)
        return {"cost_usd": cost}

    async def _h_rules_list(_p: dict[str, Any]) -> dict[str, Any]:
        rules = client.get_rules()
        return {"rules": [dto_to_dict(r) for r in rules]}

    async def _h_skills_list(_p: dict[str, Any]) -> dict[str, Any]:
        skills = client.get_skills()
        return {"skills": [dto_to_dict(s) for s in skills]}

    async def _h_skills_toggle(p: dict[str, Any]) -> dict[str, Any]:
        name = p.get("name", "")
        if not name:
            raise RpcError(INVALID_PARAMS, "name required", {"kind": "invalid_params"})
        new_hidden = client.toggle_skill(name)
        return {"enabled": not new_hidden}

    async def _h_workspace_roots(_p: dict[str, Any]) -> dict[str, Any]:
        roots = client.get_workspace_roots()
        return {"roots": [dto_to_dict(r) for r in roots]}

    async def _h_workspace_add(p: dict[str, Any]) -> dict[str, Any]:
        path = p.get("path", "")
        if not path:
            raise RpcError(INVALID_PARAMS, "path required", {"kind": "invalid_params"})
        scope = p.get("scope", "session")
        client.add_workspace_root(path, scope=scope)
        return {"added": True}

    async def _h_workspace_remove(p: dict[str, Any]) -> dict[str, Any]:
        path = p.get("path", "")
        if not path:
            raise RpcError(INVALID_PARAMS, "path required", {"kind": "invalid_params"})
        removed = client.remove_workspace_root(path)
        return {"removed": removed}

    async def _h_worktree_list(p: dict[str, Any]) -> dict[str, Any]:
        pdir = p.get("project_dir")
        worktrees = await client.list_worktrees_async(project_dir=pdir)
        return {"worktrees": [dto_to_dict(w) for w in worktrees]}

    async def _h_worktree_create(p: dict[str, Any]) -> dict[str, Any]:
        pdir = p.get("project_dir") or None
        bname = p.get("branch_name") or None
        base = p.get("base_branch", "HEAD")
        path, branch = await client.create_worktree_async(
            project_dir=pdir,
            branch_name=bname,
            base_branch=base,
        )
        return {"path": path, "branch": branch}

    async def _h_config_get(p: dict[str, Any]) -> dict[str, Any]:
        key = p.get("key", "")
        if not key:
            raise RpcError(INVALID_PARAMS, "key required", {"kind": "invalid_params"})
        val = _get_config_value(key, client, host)
        if val is _MISSING:
            raise RpcError(METHOD_NOT_FOUND, f"Unknown config key: {key}", {"kind": "not_found"})
        return {"key": key, "value": val}

    async def _h_config_set(p: dict[str, Any]) -> dict[str, Any]:
        key = p.get("key", "")
        if not key:
            raise RpcError(INVALID_PARAMS, "key required", {"kind": "invalid_params"})
        _set_config_value(key, p.get("value"), client, host)
        return {"updated": True}

    async def _h_task_list(p: dict[str, Any]) -> dict[str, Any]:
        kind = p.get("kind", "shell")
        sid = p.get("session_id")
        tasks = client.get_tasks(kind=kind, session_id=sid)
        return {"tasks": [dto_to_dict(t) for t in tasks]}

    async def _h_task_kill(p: dict[str, Any]) -> dict[str, Any]:
        tid = p.get("task_id", "")
        if not tid:
            raise RpcError(INVALID_PARAMS, "task_id required", {"kind": "invalid_params"})
        killed = await client.kill_task(tid)
        return {"killed": killed}

    async def _h_sandbox_toggle(_p: dict[str, Any]) -> dict[str, Any]:
        new_state = client.toggle_sandbox()
        host.sandbox_enabled = new_state
        return {"sandbox_enabled": new_state}

    async def _h_sandbox_state(_p: dict[str, Any]) -> dict[str, Any]:
        return {"sandbox_enabled": bool(client.sandbox)}

    async def _h_interaction_resolve(p: dict[str, Any]) -> dict[str, Any]:
        await resolve_interaction(p)
        return {"resolved": True}

    # ── Method dispatch table ──────────────────────────────────────────

    _METHODS: dict[str, Any] = {
        "daemon.info": _h_daemon_info,
        "daemon.shutdown": _h_daemon_shutdown,
        "session.list": _h_session_list,
        "session.create": _h_session_create,
        "session.resume": _h_session_resume,
        "session.delete": _h_session_delete,
        "session.export": _h_session_export,
        "prompt.stream": _h_prompt_stream,
        "prompt": _h_prompt,
        "compact": _h_compact,
        "rewind.points": _h_rewind_points,
        "provider.list": _h_provider_list,
        "model.info": _h_model_info,
        "model.estimate_cost": _h_model_estimate_cost,
        "rules.list": _h_rules_list,
        "skills.list": _h_skills_list,
        "skills.toggle": _h_skills_toggle,
        "workspace.roots": _h_workspace_roots,
        "workspace.add": _h_workspace_add,
        "workspace.remove": _h_workspace_remove,
        "worktree.list": _h_worktree_list,
        "worktree.create": _h_worktree_create,
        "config.get": _h_config_get,
        "config.set": _h_config_set,
        "task.list": _h_task_list,
        "task.kill": _h_task_kill,
        "sandbox.toggle": _h_sandbox_toggle,
        "sandbox.state": _h_sandbox_state,
        "interaction.resolve": _h_interaction_resolve,
    }

    # ── Main read loop ─────────────────────────────────────────────────
    try:
        while not shutting_down:
            try:
                line = await stream_reader.readline()
            except asyncio.CancelledError:
                break
            except Exception:
                break

            if not line:  # EOF
                break

            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            # Parse JSON
            try:
                msg: dict[str, Any] = json.loads(line_str)
            except (json.JSONDecodeError, ValueError):
                await write_msg({"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error"}})
                continue

            if not isinstance(msg, dict):
                await write_msg(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Invalid Request"}}
                )
                continue

            method = msg.get("method")
            if not isinstance(method, str) or not method:
                mid = msg.get("id")
                if mid is not None:
                    await write_msg(
                        {
                            "jsonrpc": "2.0",
                            "id": mid,
                            "error": {"code": INVALID_REQUEST, "message": "Invalid Request"},
                        }
                    )
                continue

            msg_id = msg.get("id")
            params = msg.get("params")
            if not isinstance(params, dict):
                params = {}

            # Notifications (no id) — only daemon.shutdown is handled
            if msg_id is None:
                if method == "daemon.shutdown":
                    shutting_down = True
                # Other notifications: silently ignored per spec
                continue

            # Requests → dispatch as concurrent task, tracked so EOF waits
            # for in-flight turns (spec §6: finish turn, persist, then exit)
            task = asyncio.create_task(handle_request(method, msg_id, params))
            request_tasks.add(task)
            task.add_done_callback(request_tasks.discard)

    except asyncio.CancelledError:
        pass
    finally:
        if request_tasks:
            try:
                await asyncio.wait(
                    list(request_tasks),
                    timeout=5.0,
                    return_when=asyncio.ALL_COMPLETED,
                )
            except Exception:
                pass
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    return 0
