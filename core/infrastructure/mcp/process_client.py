"""
Stdio JSON-RPC 2.0 client for MCP servers.
"""

import asyncio
import collections
import logging
import os  # noqa: F401
import select  # noqa: F401
import signal  # noqa: F401
import subprocess
import sys  # noqa: F401
import threading
import time  # noqa: F401
from typing import Any, Deque, Dict, List, Optional

from core.infrastructure.mcp.base import MCPClientBase
from core.infrastructure.mcp.process_lifecycle import (
    STDERR_TAIL_LINES,
    MCPProcessLifecycleMixin,
)
from core.infrastructure.mcp.process_protocol import MCPProcessProtocolMixin
from core.infrastructure.mcp.process_transport import MCPProcessTransportMixin

logger = logging.getLogger(__name__)

__all__ = [
    "MCPProcessClient",
    "STDERR_TAIL_LINES",
]


class MCPProcessClient(
    MCPProcessLifecycleMixin,
    MCPProcessTransportMixin,
    MCPProcessProtocolMixin,
    MCPClientBase,
):
    """Stdio JSON-RPC 2.0 client for MCP servers with Async Multiplexing support."""

    # Upper bound on cached responses kept for the sync read path. The async path
    # resolves futures directly and only caches responses so that sync
    # _read_response calls can still pick them up; without a cap this dict grows
    # unboundedly for long-running async-only sessions.
    MAX_PENDING_RESPONSES = 256

    # Used to serialize _next_req_id in thread-safe sync paths.
    _id_lock = threading.RLock()

    def __init__(
        self, name: str, command: str | List[str], cwd: Optional[str] = None, env: Optional[Dict[str, Any]] = None
    ):
        super().__init__(name, cwd=cwd, env=env)
        if isinstance(command, str):
            self.cmd = [command]
        else:
            self.cmd = list(command)
        self.process: Optional[subprocess.Popen] = None
        self._buffer = ""
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_responses: Dict[int, Dict[str, Any]] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # Bounded tail of server stderr (drained off the event loop) so a chatty
        # server can never deadlock on a full pipe; also available as diagnostics.
        self._stderr_tail: Deque[str] = collections.deque(maxlen=STDERR_TAIL_LINES)
        self._queue: Optional[asyncio.Queue] = None
        self._response_event = threading.Event()

    # ── Request ID generation (thread-safe) ────────────────────────────────

    def _next_req_id(self) -> int:
        with self._id_lock:
            self.req_id += 1
            return self.req_id
