import asyncio
import ipaddress
import os
import re
import socket
import tempfile
import threading
from typing import Any, Dict

import httpx

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool, truncate_output
from tools.cancel import run_cancellable
from tools.utils import MAX_TOOL_PAYLOAD_BYTES

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Johnston/0.1"
)


async def _is_private_host(url: str) -> bool:
    """True if URL resolves to a private/loopback/link-local address (SSRF guard)."""
    try:
        host = httpx.URL(url).host
    except Exception:
        return False
    if not host:
        return False
    # Literal IPv6/IPv4 fast path
    try:
        addr = ipaddress.ip_address(host.split("%")[0])
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        pass
    # Hostname: resolve; block any private/loopback result.
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror:
        # Unresolvable host: cannot classify as private. Let httpx surface the real
        # connection error rather than (falsely) blocking offline/sandboxed resolvers.
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return True
    return False


_SCRIPT_TAG_RE = re.compile(r"<\s*/?\s*script\b[^>]*>", re.IGNORECASE)


def _sanitize_web_content(text: str) -> str:
    """Strip <script>-style tags from fetched content to avoid script passthrough."""
    return _SCRIPT_TAG_RE.sub("", text)


def _convert_content_to_md_sync(
    content_bytes: bytes, suffix: str = ".html", cancel_event: threading.Event | None = None
) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name

    try:
        from tools.read import convert_doc_to_markdown_sync

        return convert_doc_to_markdown_sync(tmp_path, cancel_event=cancel_event)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def _guard_request(req: "httpx.Request") -> None:
    if await _is_private_host(str(req.url)):
        raise httpx.RequestError("private/loopback redirect target is not allowed", request=req)


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch content from HTTP/HTTPS URL and convert HTML/documents to Markdown."

    schema = {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL"},
                    "raw": {
                        "type": "boolean",
                        "description": "Return raw response without Markdown conversion (default: false)",
                    },
                },
                "required": ["url"],
            },
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False) is True:
            self._client = httpx.AsyncClient(
                follow_redirects=True, timeout=20.0, event_hooks={"request": [_guard_request]}
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and getattr(self._client, "is_closed", False) is False:
            await self._client.aclose()
            self._client = None

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        """Fetch URL content with follow_redirects=True and _is_private_host security guard."""
        args = args or {}
        url = (args.get("url") or "").strip()
        if not url:
            return ToolResult.error("params", name="url", detail="required")

        if not (url.startswith("http://") or url.startswith("https://")):
            return ToolResult.error("scheme", name=url, detail="must be http(s)")

        if await _is_private_host(url):
            return ToolResult.error("blocked", name=url, detail="private/loopback address is not allowed")

        raw_mode = bool(args.get("raw", False))

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        client = self._get_client()
        try:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                # Pre-check Content-Length to fail fast on oversized responses.
                cl = response.headers.get("content-length")
                if cl:
                    try:
                        if int(cl) > MAX_TOOL_PAYLOAD_BYTES:
                            return ToolResult.error(
                                "file", detail=f"exceeds {MAX_TOOL_PAYLOAD_BYTES // (1024 * 1024)}MB", name=url
                            )
                    except ValueError:
                        pass
                # Stream the body with a hard cap so an oversized or chunked
                # response cannot exhaust memory before the size check can trigger.
                total = 0
                chunks = []
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_TOOL_PAYLOAD_BYTES:
                        return ToolResult.error(
                            "file", detail=f"exceeds {MAX_TOOL_PAYLOAD_BYTES // (1024 * 1024)}MB", name=url
                        )
                    chunks.append(chunk)
                content_bytes = b"".join(chunks)
        except httpx.HTTPStatusError as e:
            return ToolResult.error("http", detail=f"{e.response.status_code} {e.response.reason_phrase}", name=url)
        except httpx.TimeoutException:
            return ToolResult.error("timeout", name=url)
        except Exception as e:
            return ToolResult.error("fetch", detail=str(e), name=url)

        if raw_mode:
            text_content = _sanitize_web_content(content_bytes.decode("utf-8", errors="replace"))
        else:
            from tools.read import DOC_EXTENSIONS

            url_path_ext = url.lower().split("?", 1)[0]
            url_ext = url_path_ext.rsplit(".", 1)[-1] if "." in url_path_ext else ""
            ext_map = {ext.lstrip("."): ext for ext in DOC_EXTENSIONS}
            if "application/pdf" in content_type or url_ext == "pdf":
                suffix = ".pdf"
            elif (
                "application/vnd.openxmlformats-officedocument.wordprocessingml" in content_type
                or url_ext == "docx"
            ):
                suffix = ".docx"
            elif "application/vnd.openxmlformats-officedocument.spreadsheetml" in content_type or url_ext == "xlsx":
                suffix = ".xlsx"
            elif url_ext in ext_map and url_ext != "pdf":
                # Reuse the shared read DOC_EXTENSIONS table for the remaining
                # convertible office formats (pptx, epub, ...).
                suffix = ext_map[url_ext]
            else:
                suffix = ".html"

            if "json" in content_type or "text/plain" in content_type:
                text_content = _sanitize_web_content(content_bytes.decode("utf-8", errors="replace"))
            else:
                try:
                    # run_cancellable auto-wires its own cancel_event into
                    # _convert_content_to_md_sync (which accepts one), so a cancelled
                    # fetch aborts the subprocess/worker promptly without explicit wiring.
                    text_content = await run_cancellable(_convert_content_to_md_sync, content_bytes, suffix)
                except Exception:
                    text_content = _sanitize_web_content(content_bytes.decode("utf-8", errors="replace"))

        if raw_mode:
            if "json" in content_type:
                out_ext = ".json"
            elif "html" in content_type:
                out_ext = ".html"
            elif "xml" in content_type:
                out_ext = ".xml"
            elif "csv" in content_type:
                out_ext = ".csv"
            else:
                out_ext = ".txt"
        else:
            if "json" in content_type:
                out_ext = ".json"
            elif "text/plain" in content_type:
                out_ext = ".txt"
            else:
                out_ext = ".md"

        return ToolResult.done(
            truncate_output(
                text_content,
                max_chars=8000,
                tool_name="web_fetch",
                ext=out_ext,
            )
        )
