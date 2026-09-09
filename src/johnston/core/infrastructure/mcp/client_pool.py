"""MCP client lifecycle: start serialization, teardown, status.

Extracted from ``MCPManager``. Operates on the manager's client registry
(``clients``), the per-server start locks that serialize client creation (so
concurrent warmup callers share one process instead of double-spawning npx),
the generation guard that aborts in-flight warmups after ``stop_all``, and the
remembered start-error map the UI reads for ERR badges after a failed start.
"""

import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MCPClientPool:
    """Coordinates MCP client lifecycle over the manager's registry."""

    def __init__(self, manager) -> None:
        self._mgr = manager

    # -- lifecycle -----------------------------------------------------------

    def stop_all(self) -> None:
        """Stop every client process and drop the registry.

        Clients are registered BEFORE their process starts, so every
        half-started client is stopped here even though the warmup task never
        completed. The generation bump aborts any warmup coroutine still in
        flight before it spawns a fresh process for the now-inactive manager.
        """
        self._mgr._generation += 1
        self._mgr._start_locks.clear()
        self._mgr._server_errors.clear()
        for client in list(self._mgr.clients.values()):
            stop = getattr(client, "stop", None)
            if not callable(stop):
                continue
            try:
                stop()
            except Exception:
                logger.warning("Failed to stop MCP client", exc_info=True)
        self._mgr.clients.clear()

    async def stop_all_async(self) -> None:
        """Stop every client process concurrently without blocking."""
        self._mgr._generation += 1
        self._mgr._start_locks.clear()
        self._mgr._server_errors.clear()
        clients = list(self._mgr.clients.values())
        self._mgr.clients.clear()
        if clients:
            coros = []
            for client in clients:
                stop_async = getattr(client, "stop_async", None)
                if callable(stop_async):
                    coros.append(stop_async())
                else:
                    stop = getattr(client, "stop", None)
                    if callable(stop):
                        coros.append(asyncio.to_thread(stop))
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)

    def stop_client(self, name: str) -> None:
        """Stop and drop one client (used when a server is disabled).

        A deliberate disable is not a failure: any remembered start error is
        dropped so re-enabling starts with a clean status.
        """
        client = self._mgr.clients.get(name)
        if client is not None:
            try:
                client.stop()
            except Exception:
                logger.warning("Failed to stop MCP client %s", name, exc_info=True)
            del self._mgr.clients[name]
        self._mgr._server_errors.pop(name, None)

    def tools_fetch_stale(self, server_name: str, ttl: float = 300.0) -> bool:
        client = self._mgr.clients.get(server_name)
        if client is None:
            return False
        return bool(client.is_tools_stale(ttl=ttl))

    # -- warmup ----------------------------------------------------------------

    async def load_server_tools_async(self, server: Dict[str, Any], timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Start (or refresh) a single MCP server and return its raw tools.

        Isolated per server with a short deadline so one slow/broken server can
        never block the others: any failure yields an empty list for that server
        only. A per-server lock serializes client creation: concurrent callers
        share the first spawned process instead of double-starting npx. Clients
        are registered BEFORE their subprocess starts so ``stop_all`` can always
        reach and terminate a half-started server.
        """
        name = server["name"]
        url = server.get("url")
        cmd = server.get("command")
        if not url and not cmd:
            return []

        gen = self._mgr._generation
        lock = self._mgr._start_locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._mgr._start_locks[name] = lock

        async with lock:
            if self._mgr._generation != gen:
                # The manager was stopped while we waited for the lock:
                # spawning a client now would resurrect processes for a dead
                # project.
                return []

            client = self._mgr.clients.get(name)
            created = client is None
            if created:
                client = self._mgr._create_client(server)
                # Register before starting: a concurrent stop_all() iterates
                # clients, so a half-started process must already be reachable.
                self._mgr.clients[name] = client

            try:
                if created:
                    try:
                        ok = await asyncio.wait_for(client.start_async(), timeout=timeout)
                    except asyncio.TimeoutError:
                        client.last_error = client.last_error or f"Server start timed out after {timeout}s"
                        await self._teardown_unready_client(name, client)
                        return []
                    except asyncio.CancelledError:
                        # The surrounding warmup task was cancelled (e.g. by
                        # stop_all): never orphan the spawned subprocess.
                        await self._teardown_unready_client(name, client)
                        raise
                    except Exception as exc:
                        if not client.last_error:
                            client.last_error = str(exc)
                        await self._teardown_unready_client(name, client)
                        return []
                    if not ok:
                        if not client.last_error:
                            client.last_error = "Failed to start"
                        await self._teardown_unready_client(name, client)
                        return []
                    if self._mgr._generation != gen:
                        await self._teardown_unready_client(name, client)
                        return []
                    # A previous failed attempt may have left a remembered
                    # error; the server now started cleanly.
                    self._mgr._server_errors.pop(name, None)
                elif self.tools_fetch_stale(name):
                    try:
                        await asyncio.wait_for(client.fetch_tools_async(), timeout=timeout)
                    except Exception:
                        logger.warning("Failed to fetch tools asynchronously for MCP server %s", name, exc_info=True)

                return list(client.tools)
            except Exception:
                logger.warning("MCP server %s failed to load tools", name, exc_info=True)
                return []

    async def _teardown_unready_client(self, name: str, client: Any) -> None:
        """Stop a client that must not stay alive and drop it from the cache.

        Remembering its fatal ``last_error`` keeps the UI showing an ERR badge
        after a failed start instead of a bare ON row — but only when this
        attempt still owns the cache slot (see the guard below).
        """
        try:
            await client.stop_async()
        except Exception:
            logger.debug("Failed to stop unready MCP client %s", name, exc_info=True)
        finally:
            # The spawned process itself must always be stopped above, but the
            # shared caches are only mutated when this attempt still owns the
            # slot: a stale attempt that lost the post-start generation race
            # (stop_all + a newer successful warmup) would otherwise pop the
            # replacement client — leaking its live subprocess — and overwrite
            # the fresh server's clean status with its own remembered error.
            if self._mgr.clients.get(name) is client:
                err = getattr(client, "last_error", None)
                if err:
                    self._mgr._server_errors[name] = err
                self._mgr.clients.pop(name, None)

    # -- status ---------------------------------------------------------------

    def get_server_status(self, server_name: str) -> Dict[str, Any]:
        """Public, internals-free status snapshot for one MCP server (UI rendering).

        Returns the discovered tool count, last error and whether the client
        process is running. UI layers should use this instead of poking at
        ``clients`` / ``client.tools`` / ``client.last_error`` directly. Errors
        from failed starts survive client teardown via the per-server error map.
        """
        stored_err = self._mgr._server_errors.get(server_name)
        client = self._mgr.clients.get(server_name)
        if client is None:
            return {"server": server_name, "tools": 0, "error": stored_err, "running": False}
        proc = getattr(client, "process", None)
        running = False
        if proc is not None:
            try:
                running = proc.poll() is None
            except Exception:
                running = False
        err = getattr(client, "last_error", None) or stored_err
        tools = getattr(client, "tools", None) or []
        return {"server": server_name, "tools": len(tools), "error": err, "running": running}


__all__ = ["MCPClientPool"]
