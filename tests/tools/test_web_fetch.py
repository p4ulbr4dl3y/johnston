import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from tools.web_fetch import WebFetchTool


def _make_stream_client(content_bytes, content_type="text/html", status_code=200, url="https://example.com"):
    """Build a MagicMock chain emulating httpx.AsyncClient.stream() used by WebFetchTool.

    WebFetchTool now streams the body (client.stream("GET", ...) -> async cm -> aiter_bytes)
    so it can enforce a size cap without loading an oversized response into memory.
    """
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}

    def _raise_for_status():
        if status_code >= 400:
            req = httpx.Request("GET", url)
            r = httpx.Response(status_code, request=req)
            raise httpx.HTTPStatusError(f"{status_code} Client Error", request=req, response=r)

    response.raise_for_status = _raise_for_status

    async def _aiter_bytes():
        yield content_bytes

    response.aiter_bytes = _aiter_bytes

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.stream = MagicMock(return_value=cm)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestWebFetchTool(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_url_scheme(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": "ftp://example.com"}))
        self.assertIn("ERR: scheme 'ftp://example.com': must be http(s)", res)

    async def test_missing_url(self):
        tool = WebFetchTool()
        res = str(await tool.execute({"url": ""}))
        self.assertIn("ERR: params 'url': required", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_html_converted(self, mock_client_cls):
        body = b"<html><body><h1>Web Page</h1><p>Test paragraph</p></body></html>"
        mock_client_cls.return_value = _make_stream_client(body, "text/html; charset=utf-8")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com"}))

        self.assertIn("Web Page", res)
        self.assertIn("Test paragraph", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_raw_mode(self, mock_client_cls):
        body = b"<div>Raw HTML</div>"
        mock_client_cls.return_value = _make_stream_client(body, "text/html")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com", "raw": True}))

        self.assertIn("<div>Raw HTML</div>", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_json_content(self, mock_client_cls):
        body = b'{"status": "ok"}'
        mock_client_cls.return_value = _make_stream_client(body, "application/json", url="https://api.example.com/data")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://api.example.com/data"}))

        self.assertIn('{"status": "ok"}', res)

    async def test_fetch_http_error(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = _make_stream_client(
                b"", "text/html", status_code=404, url="https://example.com/404"
            )
            tool = WebFetchTool()
            res = str(await tool.execute({"url": "https://example.com/404"}))

        self.assertIn("ERR: http 'https://example.com/404': 404 Not Found", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_oversize_content_length_rejected(self, mock_client_cls):
        # A Content-Length header above the cap must be rejected before the body is
        # streamed into memory, preventing OOM on oversized responses.
        from tools.utils import MAX_TOOL_PAYLOAD_BYTES

        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html", "content-length": str(MAX_TOOL_PAYLOAD_BYTES + 1)}
        response.raise_for_status = MagicMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)

        client = MagicMock()
        client.stream = MagicMock(return_value=cm)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = client

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/big"}))
        self.assertIn("ERR: file 'https://example.com/big': exceeds 10MB", res)

    @patch("httpx.AsyncClient")
    async def test_truncation_behavior(self, mock_client_cls):
        long_body = b"x" * 10000
        mock_client = _make_stream_client(long_body, "text/plain")
        mock_client_cls.return_value = mock_client

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/long"}))

        self.assertIn("Output truncated: showing first 8000 chars", res)
        self.assertIn("Full log:", res)

    async def test_convert_content_to_md_sync_unlink_oserror(self):
        # A failing tmp-file cleanup must be swallowed while the converted
        # markdown is still returned.
        from tools.web_fetch import _convert_content_to_md_sync

        with (
            patch("tools.read.convert_doc_to_markdown_sync", return_value="converted md"),
            patch("os.unlink", side_effect=OSError("file in use")),
        ):
            res = _convert_content_to_md_sync(b"<p>hi</p>", ".html")
        self.assertEqual(res, "converted md")

    @patch("httpx.AsyncClient")
    async def test_fetch_invalid_content_length_ignored(self, mock_client_cls):
        # A non-numeric Content-Length must be ignored, not crash the fetch.
        body = b"plain body"
        mock_client_cls.return_value = _make_stream_client(body, "text/plain", url="https://example.com/x")
        mock_client_cls.return_value.stream.return_value.__aenter__.return_value.headers = {
            "content-type": "text/plain",
            "content-length": "garbage",
        }

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/x"}))
        self.assertIn("plain body", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_streamed_oversize_rejected(self, mock_client_cls):
        # A chunked response without a Content-Length header must still be
        # capped at MAX_TOOL_PAYLOAD_BYTES while streaming.
        from tools.utils import MAX_TOOL_PAYLOAD_BYTES

        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.raise_for_status = MagicMock()

        async def _aiter_bytes():
            yield b"x" * MAX_TOOL_PAYLOAD_BYTES
            yield b"overflow"

        response.aiter_bytes = _aiter_bytes

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=False)

        client = MagicMock()
        client.stream = MagicMock(return_value=cm)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = client

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/big"}))
        self.assertIn("ERR: file 'https://example.com/big': exceeds 10MB", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_timeout_exception(self, mock_client_cls):
        client = MagicMock()
        client.stream.side_effect = httpx.TimeoutException("timed out")
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = client

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com"}))
        self.assertEqual(res, "ERR: timeout 'https://example.com'")

    @patch("httpx.AsyncClient")
    async def test_fetch_generic_exception(self, mock_client_cls):
        client = MagicMock()
        client.stream.side_effect = httpx.ConnectError("connection refused")
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = client

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com"}))
        self.assertIn("ERR: fetch 'https://example.com': connection refused", res)

    @patch("httpx.AsyncClient")
    @patch("tools.read.convert_doc_to_markdown_sync", side_effect=RuntimeError("no converter"))
    async def test_fetch_pdf_conversion_fallback(self, mock_convert, mock_client_cls):
        body = b"%PDF-1.4 fake body"
        mock_client_cls.return_value = _make_stream_client(body, "application/pdf")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/doc.pdf"}))
        self.assertIn("%PDF-1.4 fake body", res)

    @patch("httpx.AsyncClient")
    @patch("tools.read.convert_doc_to_markdown_sync", side_effect=RuntimeError("no converter"))
    async def test_fetch_docx_conversion_fallback(self, mock_convert, mock_client_cls):
        body = b"PK\x03\x04 fake docx"
        mock_client_cls.return_value = _make_stream_client(
            body, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/doc.docx"}))
        self.assertIn("PK\x03\x04 fake docx", res)

    @patch("httpx.AsyncClient")
    @patch("tools.read.convert_doc_to_markdown_sync", side_effect=RuntimeError("no converter"))
    async def test_fetch_xlsx_conversion_fallback(self, mock_convert, mock_client_cls):
        body = b"PK\x03\x04 fake xlsx"
        mock_client_cls.return_value = _make_stream_client(
            body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/data.xlsx"}))
        self.assertIn("PK\x03\x04 fake xlsx", res)

    @patch("httpx.AsyncClient")
    async def test_truncation_saves_md_by_default(self, mock_client_cls):
        body = b"<h1>Title</h1>" + (b"<p>paragraph</p>" * 1000)
        mock_client_cls.return_value = _make_stream_client(body, "text/html")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/page"}))
        self.assertIn("Full log:", res)
        self.assertIn(".md", res)

    @patch("httpx.AsyncClient")
    async def test_truncation_raw_html_saves_html(self, mock_client_cls):
        body = b"<div>" + (b"long raw html content " * 1000) + b"</div>"
        mock_client_cls.return_value = _make_stream_client(body, "text/html")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://example.com/raw_page", "raw": True}))
        self.assertIn("Full log:", res)
        self.assertIn(".html", res)

    @patch("httpx.AsyncClient")
    @patch("socket.getaddrinfo")
    async def test_fake_ip_proxy_range_allowed(self, mock_gai, mock_client_cls):
        # 198.18.0.0/15 fake-IP used by proxies/VPNs must not be blocked as private
        mock_gai.return_value = [(2, 1, 6, "", ("198.18.0.14", 0))]
        body = b"<html><body><h1>GitHub</h1></body></html>"
        mock_client_cls.return_value = _make_stream_client(body, "text/html")

        tool = WebFetchTool()
        res = str(await tool.execute({"url": "https://github.com/repo"}))
        self.assertIn("# GitHub", res)

    @patch("socket.getaddrinfo")
    async def test_private_lan_and_loopback_blocked(self, mock_gai):
        tool = WebFetchTool()
        for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.1.1"):
            mock_gai.return_value = [(2, 1, 6, "", (ip, 0))]
            res = str(await tool.execute({"url": "http://internal-service.local/"}))
            self.assertIn("blocked", res)


if __name__ == "__main__":
    unittest.main()
