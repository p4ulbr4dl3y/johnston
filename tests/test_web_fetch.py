import unittest
from unittest.mock import MagicMock, patch

import httpx

from tools.web_fetch import WebFetchTool


class TestWebFetchTool(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_url_scheme(self):
        tool = WebFetchTool()
        res = await tool.execute({"url": "ftp://example.com"})
        self.assertIn("Error: invalid URL scheme", res)

    async def test_missing_url(self):
        tool = WebFetchTool()
        res = await tool.execute({"url": ""})
        self.assertIn("Error: parameter 'url' is required", res)

    @patch("httpx.AsyncClient.get")
    async def test_fetch_html_converted(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.content = b"<html><body><h1>Web Page</h1><p>Test paragraph</p></body></html>"
        mock_resp.text = "<html><body><h1>Web Page</h1><p>Test paragraph</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://example.com"})

        self.assertIn("Web Page", res)
        self.assertIn("Test paragraph", res)

    @patch("httpx.AsyncClient.get")
    async def test_fetch_raw_mode(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.content = b"<div>Raw HTML</div>"
        mock_resp.text = "<div>Raw HTML</div>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://example.com", "raw": True})

        self.assertIn("<div>Raw HTML</div>", res)

    @patch("httpx.AsyncClient.get")
    async def test_fetch_json_content(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.content = b'{"status": "ok"}'
        mock_resp.text = '{"status": "ok"}'
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://api.example.com/data"})

        self.assertIn('{"status": "ok"}', res)

    @patch("httpx.AsyncClient.get")
    async def test_fetch_http_error(self, mock_get):
        req = httpx.Request("GET", "https://example.com/404")
        resp = httpx.Response(404, request=req, json={"detail": "Not found"})
        mock_get.side_effect = httpx.HTTPStatusError("404 Client Error", request=req, response=resp)

        tool = WebFetchTool()
        res = await tool.execute({"url": "https://example.com/404"})

        self.assertIn("Error fetching 'https://example.com/404': HTTP 404", res)


if __name__ == "__main__":
    unittest.main()
