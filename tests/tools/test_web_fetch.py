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
        res = await tool.execute({"url": "ftp://example.com"})
        self.assertIn("Error: invalid URL scheme", res)

    async def test_missing_url(self):
        tool = WebFetchTool()
        res = await tool.execute({"url": ""})
        self.assertIn("Error: parameter 'url' is required", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_html_converted(self, mock_client_cls):
        body = b"<html><body><h1>Web Page</h1><p>Test paragraph</p></body></html>"
        mock_client_cls.return_value = _make_stream_client(body, "text/html; charset=utf-8")

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://example.com"})

        self.assertIn("Web Page", res)
        self.assertIn("Test paragraph", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_raw_mode(self, mock_client_cls):
        body = b"<div>Raw HTML</div>"
        mock_client_cls.return_value = _make_stream_client(body, "text/html")

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://example.com", "raw": True})

        self.assertIn("<div>Raw HTML</div>", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_json_content(self, mock_client_cls):
        body = b'{"status": "ok"}'
        mock_client_cls.return_value = _make_stream_client(body, "application/json", url="https://api.example.com/data")

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://api.example.com/data"})

        self.assertIn('{"status": "ok"}', res)

    async def test_fetch_http_error(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = _make_stream_client(b"", "text/html", status_code=404, url="https://example.com/404")
            tool = WebFetchTool()
            res = await tool.execute({"url": "https://example.com/404"})

        self.assertIn("Error fetching 'https://example.com/404': HTTP 404", res)

    @patch("httpx.AsyncClient")
    async def test_fetch_oversize_content_length_rejected(self, mock_client_cls):
        # A Content-Length header above the cap must be rejected before the body is
        # streamed into memory, preventing OOM on oversized responses.
        from tools.web_fetch import MAX_RESPONSE_SIZE

        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html", "content-length": str(MAX_RESPONSE_SIZE + 1)}
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
        res = await tool.execute({"url": "https://example.com/big"})
        self.assertIn("exceeds max allowed size", res)

    @patch("httpx.AsyncClient")
    async def test_truncation_behavior(self, mock_client_cls):
        long_body = (b"x" * 10000)
        mock_client = _make_stream_client(long_body, "text/plain")
        mock_client_cls.return_value = mock_client

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://example.com/long"})

        self.assertIn("Output truncated at 8000 chars", res)
        self.assertIn("Full output saved to", res)


if __name__ == "__main__":
    unittest.main()

