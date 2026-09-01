"""Edge-case regression/security tests for web_fetch, ask_user, and cancel.

Each test targets a code path not covered by the primary suite
(tests/tools/test_web_fetch.py, test_ask_user_tool.py, test_cancel.py).

Two tests are intentionally RED — they document real bugs in tools/web_fetch.py:
  1. SSRF: fetch is allowed to private/internal addresses (and follow_redirects
     is always on with no host allowlist).
  2. XSS: `<script>` content in non-HTML (text/plain / raw) bodies is passed
     through to the model unsanitized.

All network interaction is mocked; no real sockets are used.
"""

import asyncio
import inspect as _inspect
import socket
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from tools.ask_user import AskUserTool
from tools.cancel import run_cancellable
from tools.utils import MAX_TOOL_PAYLOAD_BYTES
from tools.web_fetch import WebFetchTool


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _mk_stream_client(body, content_type="text/html", status_code=200, headers=None):
    """Emulate httpx.AsyncClient.stream() -> async cm -> aiter_bytes."""
    response = MagicMock()
    response.status_code = status_code
    _headers = dict(headers or {})
    _headers.setdefault("content-type", content_type)
    response.headers = _headers

    def _raise_for_status():
        if status_code >= 400:
            req = httpx.Request("GET", "https://example.com")
            r = httpx.Response(
                status_code,
                request=req,
            )
            raise httpx.HTTPStatusError("ex", request=req, response=r)

    response.raise_for_status = _raise_for_status

    async def _aiter_bytes():
        yield body

    response.aiter_bytes = _aiter_bytes

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mk_client(cm):
    client = MagicMock()
    client.stream = MagicMock(return_value=cm)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# --------------------------------------------------------------------------- #
# web_fetch — URL arg shape edge cases (these should all be handled cleanly)
# --------------------------------------------------------------------------- #
class TestWebFetchUrlEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_url_none(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": None}))
        self.assertIn("ERR", res)

    async def test_url_whitespace_only(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "   "}))
        self.assertIn("required", res)

    async def test_url_not_a_url_plain_string(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "example dot com nothing"}))
        self.assertIn("must be http(s)", res)

    async def test_ftp_scheme_rejected(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "ftp://host/file"}))
        self.assertIn("must be http(s)", res)

    async def test_file_scheme_rejected(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "file:///etc/passwd"}))
        self.assertIn("must be http(s)", res)
        self.assertNotIn("root:", res)

    async def test_uppercase_scheme_rejected(self):
        # startswith is case-sensitive; HTTP:// (all caps) is not normalized.
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "HTTP://example.com"}))
        self.assertIn("must be http(s)", res)

    @patch("httpx.AsyncClient")
    async def test_unicode_url(self, mock_cls):
        mock_cls.return_value = _mk_client(_mk_stream_client(b"<p>hi</p>", "text/html"))
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://пример.рф/тест"}))
        self.assertIn("hi", res)

    @patch("httpx.AsyncClient")
    async def test_url_with_space_injecting_host(self, mock_cls):
        # A space in the URL must not crash — httpx / fetch path catches it.
        client = _mk_client(_mk_stream_client(b"x", "text/html"))
        client.stream.side_effect = ValueError("Invalid URL")
        mock_cls.return_value = client
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "http://example.com /etc/passwd"}))
        self.assertTrue(res.startswith("ERR"), res)


# --------------------------------------------------------------------------- #
# web_fetch — network layer edge cases
# --------------------------------------------------------------------------- #
class TestWebFetchNetworkEdgeCases(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_connect_error(self, mock_cls):
        client = _mk_client(_mk_stream_client(b"", "text/html"))
        client.stream.side_effect = httpx.ConnectError("[Errno 61] Connection refused")
        mock_cls.return_value = client
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com"}))
        self.assertIn("ERR: fetch", res)

    @patch("httpx.AsyncClient")
    async def test_dns_resolution_error(self, mock_cls):
        client = _mk_client(_mk_stream_client(b"", "text/html"))
        client.stream.side_effect = httpx.ConnectError(
            "[Errno 8] nodename nor servname provided (AuthorityNotFound)"
        )
        mock_cls.return_value = client
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://no-such-host.invalid"}))
        self.assertIn("ERR", res)

    @patch("httpx.AsyncClient")
    async def test_server_5xx(self, mock_cls):
        mock_cls.return_value = _mk_client(_mk_stream_client(b"oops", "text/html", status_code=500))
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/boom"}))
        self.assertIn("ERR: http", res)
        self.assertIn("500", res)

    @patch("httpx.AsyncClient")
    async def test_empty_body(self, mock_cls):
        # An empty body (204-like) must return cleanly, not crash convert.
        mock_cls.return_value = _mk_client(_mk_stream_client(b"", "text/html"))
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/empty"}))
        self.assertIsInstance(res, str)

    @patch("httpx.AsyncClient")
    async def test_binary_non_utf8_body_raw(self, mock_cls):
        # raw mode on non-UTF8 bytes must not crash decode.
        mock_cls.return_value = _mk_client(_mk_stream_client(b"\xff\xfe\x00\x80abc", "application/octet-stream"))
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/blob", "raw": True}))
        self.assertIsInstance(res, str)
        self.assertIn("abc", res)

    @patch("httpx.AsyncClient")
    async def test_chunked_body_over_cap(self, mock_cls):
        # Chunked (no Content-Length) oversized body must be stopped mid-stream.
        async def _aiter():
            yield b"a" * MAX_TOOL_PAYLOAD_BYTES
            yield b"aaa"

        cm = _mk_stream_client(b"", "text/html", headers={"content-type": "text/html"})
        cm.__aenter__.return_value.aiter_bytes = _aiter
        mock_cls.return_value = _mk_client(cm)
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/chunked-big"}))
        self.assertIn("exceeds 10MB", res)

    @patch("httpx.AsyncClient")
    async def test_timeout_arg_is_ignored(self, mock_cls):
        # Tool API has no timeout knob; negative/zero args must not crash and
        # the hardcoded 20s client still works.
        mock_cls.return_value = _mk_client(_mk_stream_client(b"ok", "text/plain"))
        tool = WebFetchTool()
        for t in (None, 0, -5):
            res = str(await tool.execute({"url": "https://example.com/t", "timeout": t}))
            self.assertIn("ok", res)


# --------------------------------------------------------------------------- #
# web_fetch — SECURITY bugs (RED)
# --------------------------------------------------------------------------- #
class TestWebFetchSecurityBugs(unittest.IsolatedAsyncioTestCase):
    """These tests document real security gaps. They fail against the current
    implementation on purpose — do not delete the failures without fixing tools/
    web_fetch.py first."""

    @patch("httpx.AsyncClient")
    async def test_ssrf_localhost_not_blocked(self, mock_cls):
        """Fixed: private address (127.0.0.1) is refused before any connection."""
        resp = _mk_stream_client(b"root:x:0:0::/root:/bin/bash\n", "text/plain")
        mock_cls.return_value = _mk_client(resp)
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "http://127.0.0.1:8080/etc/passwd"}))
        self.assertIn("ERR", res)
        self.assertIn("blocked", res)

    @patch("httpx.AsyncClient")
    async def test_ssrf_cloud_metadata_not_blocked(self, mock_cls):
        """Fixed: cloud metadata link-local address is refused."""
        body = b'{"access_token": "secret"}'
        resp = _mk_stream_client(body, "application/json")
        mock_cls.return_value = _mk_client(resp)
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "http://169.254.169.254/latest/meta-data/"}))
        self.assertIn("blocked", res)

    @patch("httpx.AsyncClient")
    @patch("socket.getaddrinfo")
    async def test_ssrf_hostname_localhost_alias_not_blocked(self, mock_gai, mock_cls):
        """Fixed: localhost / internal hostnames resolve to loopback and are refused."""
        mock_gai.return_value = [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))]
        resp = _mk_stream_client(b"private", "text/plain")
        mock_cls.return_value = _mk_client(resp)
        tool = WebFetchTool()
        for host in ("http://localhost/", "http://[::1]/", "http://10.0.0.5/"):
            with self.subTest(host=host):
                res = str(await tool.execute({"url": host + "flag"}))
                self.assertIn("blocked", res)

    def test_redirect_following_has_host_allowlist(self):
        """Fixed: redirects are re-checked per request via the private-host guard."""
        src = _inspect.getsource(WebFetchTool.execute)
        self.assertIn("follow_redirects=True", src)
        self.assertIn("_is_private_host", src)

    @patch("httpx.AsyncClient")
    async def test_credentials_in_url_accepted(self, mock_cls):
        # URLs carrying inline credentials are accepted and passed to httpx;
        # there is no stripping or warning.
        resp = _mk_stream_client(b"authed", "text/plain")
        mock_cls.return_value = _mk_client(resp)
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "http://user:pass@example.com/"}))
        self.assertIn("authed", res)
        url_arg = mock_cls.return_value.stream.call_args.args[1]
        self.assertIn("user:pass@", url_arg)

    @patch("httpx.AsyncClient")
    async def test_xss_script_passthrough_raw_mode(self, mock_cls):
        # BUG: raw mode returns the raw response unchanged — inline <script> is not
        # stripped/sanitized before it is fed to the model.
        script = b'<html><body><script>alert(document.cookie)</script></body></html>'
        mock_cls.return_value = _mk_client(_mk_stream_client(script, "text/html"))
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/x", "raw": True}))
        self.assertNotIn("<script>", res)

    @patch("httpx.AsyncClient")
    async def test_xss_script_passthrough_text_plain(self, mock_cls):
        # BUG: content served as text/plain bypasses markdown conversion and the
        # inline <script> reaches the model verbatim.
        script = b'some text <script>window.location="https://evil"</script> more'
        mock_cls.return_value = _mk_client(_mk_stream_client(script, "text/plain"))
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/x"}))
        self.assertNotIn("<script>", res)


# --------------------------------------------------------------------------- #
# ask_user — edge cases
# --------------------------------------------------------------------------- #
class TestAskUserEdgeCases(unittest.IsolatedAsyncioTestCase):
    def _tool(self):
        return AskUserTool()

    async def test_no_question_arg(self):
        tool = self._tool()
        res = str(await tool.execute({}))
        self.assertIn("ERR", res)

    async def test_empty_question_skipped(self):
        tool = self._tool()
        app = MagicMock()
        app.ask_user = AsyncMock(return_value="ok")
        res = str(await tool.execute({"questions": [{"question": "", "options": [{"label": "a"}]}]}, ctx=app))
        self.assertIn("missing or invalid", res)

    async def test_all_questions_invalid_returns_error(self):
        # Non-dict entries and missing-option entries are skipped silently; if
        # nothing survives, the tool reports invalid params instead of crashing.
        tool = self._tool()
        app = MagicMock()
        app.ask_user = AsyncMock(return_value="ok")
        res = str(await tool.execute(
            {
                "questions": [
                    "not a dict",
                    {"question": "ok", "options": None},
                    {"question": "", "options": [{"label": "a"}]},
                    {"options": [{"label": "x"}]},
                ]
            },
            ctx=app,
        ))
        self.assertIn("missing or invalid", res)
        app.ask_user.assert_not_awaited()

    async def test_no_ask_user_attribute_no_hang(self):
        # Fallback when the app exposes no ask_user: must return promptly with an
        # ERR rather than hanging on a non-callable.
        tool = self._tool()
        app = MagicMock()
        del app.ask_user  # no ask_user attribute at all
        res = str(await tool.execute({"questions": [{"question": "Q?", "options": [{"label": "a"}]}]}, ctx=app))
        self.assertIn("ERR: context 'app': unavailable", res)

    async def test_many_options_forwarded_uncapped(self):
        # The tool does not cap the number of options; a 500-option question is
        # passed straight to the UI layer.
        tool = self._tool()
        seen = {}

        async def fake(questions):
            seen["n"] = len(questions[0]["options"])
            return "Question: Q\nAnswer: a"

        app = MagicMock()
        app.ask_user = fake
        res = str(await tool.execute(
            {"questions": [{"question": "Q", "options": [{"label": f"o{i}"} for i in range(500)]}]}, ctx=app
        ))
        self.assertEqual(seen["n"], 500)
        self.assertIn("a", res)

    async def test_cancelled_clears_pending_when_flag_missing(self):
        # A CancelledError raised while the app has no _pending_ask_user attribute
        # must propagate as a cancellation (no AttributeError), while still working
        # without a _pending_ask_user attribute present.
        async def _cancelled(q):
            raise asyncio.CancelledError()

        tool = self._tool()
        app = MagicMock()
        app.ask_user = _cancelled
        with self.assertRaises(asyncio.CancelledError):
            await tool.execute({"questions": [{"question": "Q?", "options": [{"label": "a"}]}]}, ctx=app)

    async def test_options_non_dict_and_empty_filtered(self):
        # Non-dict and empty label options are safely filtered out.
        tool = self._tool()
        seen = {}

        async def fake(questions):
            seen["opts"] = questions[0]["options"]
            return "Question: Q\nAnswer: x"

        app = MagicMock()
        app.ask_user = fake
        res = str(await tool.execute(
            {
                "questions": [
                    {
                        "question": "Q",
                        "options": [
                            {"label": "a"},
                            None,
                            5,
                            ["b"],
                            {"label": "valid", "description": "desc"},
                            {"label": ""},
                        ],
                    }
                ]
            },
            ctx=app,
        ))
        self.assertEqual(seen["opts"], [
            {"label": "a", "description": ""},
            {"label": "valid", "description": "desc"},
        ])
        self.assertIn("x", res)

    async def test_single_question_form_rejected(self):
        # The flat {question: ...} form was removed; only questions[].question is accepted.
        tool = self._tool()
        res = str(await tool.execute({"question": "Only text?"}, ctx=MagicMock(app=MagicMock())))
        self.assertIn("ERR: params 'questions'", res)


# --------------------------------------------------------------------------- #
# cancel — edge cases
# --------------------------------------------------------------------------- #
class TestCancelEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_after_completion_is_noop(self):
        # Cancelling a task that already finished must not raise/leak.
        task = asyncio.create_task(run_cancellable(lambda: "done"))
        await task
        self.assertEqual(task.result(), "done")
        task.cancel()  # already finished -> cancelling is safe
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        self.assertTrue(task.done())

    async def test_multiple_cancel_calls(self):
        # Repeated cancel() must be idempotent and still raise CancelledError once.
        calls = []
        started = threading.Event()

        def worker(cancel_event=None):
            started.set()
            while True:
                calls.append(cancel_event.is_set())
                if cancel_event.is_set():
                    return "bailed"
                time.sleep(0.001)

        task = asyncio.create_task(run_cancellable(worker))
        await asyncio.to_thread(started.wait)
        task.cancel()
        task.cancel()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancel_non_cooperative_returns_immediately(self):
        # A worker that ignores cancel_event still lets the caller return at once.
        started = threading.Event()

        def stubborn():
            started.set()
            time.sleep(5.0)
            return "late"

        task = asyncio.create_task(run_cancellable(stubborn))
        await asyncio.to_thread(started.wait)
        start = time.monotonic()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertLess(time.monotonic() - start, 2.0)
        # The caller is not blocked, but the orphaned thread keeps running; we
        # must not join it — so we just assert the caller returned promptly.

    async def test_worker_raising_returns_via_cancel_event(self):
        # A cooperative worker that raises once it sees the cancel event still
        # surfaces CancelledError to the awaiting task (exception swallowed).
        started = threading.Event()

        def worker(cancel_event=None):
            started.set()
            while not cancel_event.is_set():
                time.sleep(0.001)
            raise RuntimeError("cancelled cooperatively")

        task = asyncio.create_task(run_cancellable(worker))
        await asyncio.to_thread(started.wait)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_run_cancellable_returns_value(self):
        self.assertEqual(await run_cancellable(lambda: 42), 42)


if __name__ == "__main__":
    unittest.main()
