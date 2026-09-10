"""Regression tests for infrastructure reliability refactoring.

Covers:
1. BaseApiAdapter resource management and async closing.
2. CircuitBreaker thread-safety, sliding window TTL, and HALF_OPEN single probe.
3. update_json_config interprocess file locking atomicity.
4. GitWorktreeManager secrets protection against symlinking .env and credentials.
"""

import concurrent.futures
import os
import subprocess
import tempfile
import unittest
from typing import Any, Dict, Optional

from johnston.core.infrastructure.llm.models.base import BaseApiAdapter
from johnston.core.infrastructure.platform.platform_utils import read_json, update_json_config
from johnston.core.infrastructure.runtime.circuit_breaker import CircuitBreaker, CircuitState
from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager


class DummyClient:
    def __init__(self, is_async: bool = True):
        self.is_async = is_async
        self.closed = False

    async def aclose(self):
        self.closed = True

    def close(self):
        self.closed = True


class DummyAdapter(BaseApiAdapter):
    def __init__(self, client: Optional[Any] = None):
        super().__init__()
        self._mock_client = client or DummyClient()

    def _create_client(self, base_url: str, api_key: str, headers: Optional[Dict[str, str]] = None) -> Any:
        return self._mock_client


class TestBaseApiAdapterResourceManagement(unittest.TestCase):
    def test_close_without_running_event_loop(self):
        client = DummyClient()
        adapter = DummyAdapter(client)
        adapter._get_client("https://api.test.com", "key1")
        self.assertFalse(client.closed)

        adapter.close()
        self.assertTrue(client.closed)
        self.assertEqual(len(adapter._clients), 0)

    def test_close_handles_sync_closer(self):
        class SyncClient:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        client = SyncClient()
        adapter = DummyAdapter(client)
        adapter._get_client("https://api.test.com", "key1")
        adapter.close()
        self.assertTrue(client.closed)


class TestBaseApiAdapterAsyncResourceManagement(unittest.IsolatedAsyncioTestCase):
    async def test_aclose_closes_all_clients(self):
        client = DummyClient()
        adapter = DummyAdapter(client)
        adapter._get_client("https://api.test.com", "key1")
        self.assertFalse(client.closed)

        await adapter.aclose()
        self.assertTrue(client.closed)
        self.assertEqual(len(adapter._clients), 0)

    async def test_sync_close_inside_running_event_loop_does_not_raise(self):
        client = DummyClient()
        adapter = DummyAdapter(client)
        adapter._get_client("https://api.test.com", "key1")

        # In an active event loop, calling adapter.close() must NOT raise RuntimeError
        adapter.close()
        self.assertEqual(len(adapter._clients), 0)


class TestCircuitBreakerReliability(unittest.TestCase):
    def test_sliding_window_ttl_pruning(self):
        # failure_threshold=3, failure_ttl_seconds=10.0
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, failure_ttl_seconds=10.0)
        provider = "prov_ttl"

        # Record 2 failures at t=1000
        cb.record_failure(provider)
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), CircuitState.CLOSED)
        self.assertEqual(len(cb._failure_timestamps.get(provider, [])), 2)

        # Manually shift timestamps back by 15s (past TTL of 10s)
        cb._failure_timestamps[provider] = [t - 15.0 for t in cb._failure_timestamps[provider]]

        # Record a 3rd failure. Since previous 2 expired, total active failures should be 1
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), CircuitState.CLOSED)
        self.assertEqual(len(cb._failure_timestamps.get(provider, [])), 1)

        # Record 2 more failures within window -> 3 failures in window -> OPEN
        cb.record_failure(provider)
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), CircuitState.OPEN)

    def test_half_open_allows_only_one_probe_until_settled(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01, failure_ttl_seconds=10.0)
        provider = "prov_half_open"

        cb.record_failure(provider)
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), CircuitState.OPEN)

        # Wait for cooldown
        import time

        time.sleep(0.015)
        self.assertEqual(cb.get_state(provider), CircuitState.HALF_OPEN)

        # 1st request allowed as trial probe
        self.assertTrue(cb.allow_request(provider))

        # 2nd request BLOCKED while probe is in flight
        self.assertFalse(cb.allow_request(provider))
        self.assertFalse(cb.allow_request(provider))

        # Probe fails -> immediately reverts to OPEN
        cb.record_failure(provider)
        self.assertEqual(cb.get_state(provider), CircuitState.OPEN)
        self.assertFalse(cb.allow_request(provider))

        # Wait for cooldown again
        time.sleep(0.015)
        self.assertEqual(cb.get_state(provider), CircuitState.HALF_OPEN)

        # 1st request allowed as trial probe
        self.assertTrue(cb.allow_request(provider))
        # 2nd request blocked
        self.assertFalse(cb.allow_request(provider))

        # Probe succeeds -> resets to CLOSED
        cb.record_success(provider)
        self.assertEqual(cb.get_state(provider), CircuitState.CLOSED)
        # All requests now allowed
        self.assertTrue(cb.allow_request(provider))
        self.assertTrue(cb.allow_request(provider))

    def test_thread_safety_under_concurrency(self):
        cb = CircuitBreaker(failure_threshold=50, cooldown_seconds=1.0, failure_ttl_seconds=10.0)
        provider = "prov_concurrent"

        def worker(idx: int):
            for _ in range(20):
                if idx % 2 == 0:
                    cb.record_failure(provider)
                else:
                    cb.allow_request(provider)
                    cb.get_state(provider)
                    cb.remaining_cooldown(provider)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(16)]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()

        # No deadlock and state remains coherent
        self.assertIn(cb.get_state(provider), (CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN))


class TestPlatformConfigLocking(unittest.TestCase):
    def test_update_json_config_concurrency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")

            def increment_counter():
                for _ in range(25):

                    def mutator(d: Dict[str, Any]):
                        d["counter"] = d.get("counter", 0) + 1

                    update_json_config(config_path, mutator)

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(increment_counter) for _ in range(4)]
                for fut in concurrent.futures.as_completed(futures):
                    fut.result()

            result = read_json(config_path)
            self.assertEqual(result.get("counter"), 100)


class TestGitWorktreeSecretsProtection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = os.path.realpath(self.temp_dir.name)

        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )

        with open(os.path.join(self.repo_dir, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Initial Main\n")

        subprocess.run(["git", "add", "."], cwd=self.repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.repo_dir, capture_output=True, text=True)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_is_secret_file_detection(self):
        self.assertTrue(GitWorktreeManager.is_secret_file(".env"))
        self.assertTrue(GitWorktreeManager.is_secret_file(".env.local"))
        self.assertTrue(GitWorktreeManager.is_secret_file(".env.production"))
        self.assertTrue(GitWorktreeManager.is_secret_file("/path/to/.env"))
        self.assertTrue(GitWorktreeManager.is_secret_file("server.key"))
        self.assertTrue(GitWorktreeManager.is_secret_file("cert.pem"))
        self.assertTrue(GitWorktreeManager.is_secret_file("id_rsa"))
        self.assertTrue(GitWorktreeManager.is_secret_file("credentials.json"))
        self.assertTrue(GitWorktreeManager.is_secret_file("api_token.txt"))

        self.assertFalse(GitWorktreeManager.is_secret_file(".venv"))
        self.assertFalse(GitWorktreeManager.is_secret_file("main.py"))
        self.assertFalse(GitWorktreeManager.is_secret_file("README.md"))

    def test_create_worktree_does_not_symlink_secrets(self):
        # Create various secret files and a valid virtualenv folder
        secrets = ["server.key", "credentials.json", "id_rsa"]
        for s in secrets:
            with open(os.path.join(self.repo_dir, s), "w", encoding="utf-8") as f:
                f.write("SECRET=123\n")

        venv_dir = os.path.join(self.repo_dir, ".venv")
        os.makedirs(venv_dir, exist_ok=True)

        branch_name = "feat/refactor-security"
        wt_path, created_branch = GitWorktreeManager.create_worktree(self.repo_dir, branch_name)

        try:
            self.assertIsNotNone(wt_path)
            self.assertEqual(created_branch, branch_name)

            # Check that none of the non-env credentials/secrets were copied or symlinked
            for s in secrets:
                wt_secret = os.path.join(wt_path, s)
                self.assertFalse(os.path.lexists(wt_secret), f"Secret file {s} was symlinked into worktree!")

            # Check that no .venv symlink/copy was created either
            wt_venv = os.path.join(wt_path, ".venv")
            self.assertFalse(os.path.lexists(wt_venv))
        finally:
            if wt_path:
                GitWorktreeManager.remove_worktree(self.repo_dir, wt_path, branch_name, delete_branch=True)
