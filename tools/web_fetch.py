import asyncio
import ipaddress
import re
import socket
import threading
import time
from typing import Any, Dict

import httpx

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool
from tools.cancel import run_cancellable
from tools.utils import get_max_tool_payload_bytes

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Johnston/0.1"
)


_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")
_DNS_CACHE: dict[str, tuple[float, bool]] = {}
_DNS_CACHE_TTL = 60.0
_MAX_DNS_CACHE = 512
_DNS_CACHE_LOCK: asyncio.Lock | None = None


def _get_dns_cache_lock() -> asyncio.Lock:
    global _DNS_CACHE_LOCK
    if _DNS_CACHE_LOCK is None:
        _DNS_CACHE_LOCK = asyncio.Lock()
    return _DNS_CACHE_LOCK


def _dns_cache_policy() -> tuple[float, int]:
    """Return the configured (ttl, max) for the SSRF DNS cache."""
    try:
        from core.infrastructure.config.settings import get_settings

        tools = get_settings().tools
        return tools.dns_cache_ttl, tools.dns_cache_max
    except Exception:
        return _DNS_CACHE_TTL, _MAX_DNS_CACHE


def _web_user_agent() -> str:
    """Return the configured User-Agent for HTTP fetches."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools.web_user_agent
    except Exception:
        return DEFAULT_USER_AGENT


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # 198.18.0.0/15 is used by transparent proxies / VPNs (Clash, Surge, Sing-box) as Fake-IP pool
    # Normalize IPv4-mapped IPv6 (e.g. ::ffff:198.18.0.21) so the Fake-IP exemption
    # (and private-address checks) apply uniformly.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv4Address) and addr in _FAKE_IP_NET:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


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
        return _is_blocked_ip(addr)
    except ValueError:
        pass

    now = time.monotonic()
    cache_ttl, cache_max = _dns_cache_policy()
    lock = _get_dns_cache_lock()
    async with lock:
        cached = _DNS_CACHE.get(host)
        if cached is not None:
            cached_ts, cached_res = cached
            if now - cached_ts < cache_ttl:
                return cached_res
            _DNS_CACHE.pop(host, None)

    # Hostname: resolve; block any private/loopback result.
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror:
        # Unresolvable host: cannot classify as private. Let httpx surface the real
        # connection error rather than (falsely) blocking offline/sandboxed resolvers.
        return False
    except Exception:
        return False

    is_blocked = False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_blocked_ip(addr):
            is_blocked = True
            break

    async with lock:
        if len(_DNS_CACHE) >= cache_max:
            _DNS_CACHE.clear()
        _DNS_CACHE[host] = (now, is_blocked)
    return is_blocked



_SCRIPT_TAG_RE = re.compile(r"<\s*/?\s*script\b[^>]*>", re.IGNORECASE)


def _sanitize_web_content(text: str) -> str:
    """Strip <script>-style tags from fetched content to avoid script passthrough."""
    return _SCRIPT_TAG_RE.sub("", text)


def _convert_content_to_md_sync(
    content_bytes: bytes, suffix: str = ".html", cancel_event: threading.Event | None = None
) -> str:
    if cancel_event and cancel_event.is_set():
        return ""
    from core.infrastructure.converter import convert_bytes

    return convert_bytes(content_bytes, suffix)


async def _guard_request(req: "httpx.Request") -> None:
    if await _is_private_host(str(req.url)):
        raise httpx.RequestError("private/loopback redirect target is not allowed", request=req)


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch content from HTTP/HTTPS URL and convert HTML/documents (PDF, DOCX, XLSX, etc.) to Markdown."

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

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return True

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False) is True:
            from core.infrastructure.config.settings import get_settings

            try:
                timeout = get_settings().tools.web_fetch_timeout
            except Exception:
                timeout = 20.0
            self._client = httpx.AsyncClient(
                follow_redirects=True, timeout=timeout, event_hooks={"request": [_guard_request]}
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and getattr(self._client, "is_closed", False) is False:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "WebFetchTool":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

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
            "User-Agent": _web_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        client = self._get_client()
        payload_limit = get_max_tool_payload_bytes()
        try:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                # Pre-check Content-Length to fail fast on oversized responses.
                cl = response.headers.get("content-length")
                if cl:
                    try:
                        if int(cl) > payload_limit:
                            return ToolResult.error(
                                "file", detail=f"exceeds {payload_limit // (1024 * 1024)}MB", name=url
                            )
                    except ValueError:
                        pass
                # Stream the body with a hard cap so an oversized or chunked
                # response cannot exhaust memory before the size check can trigger.
                total = 0
                chunks = []
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > payload_limit:
                        return ToolResult.error(
                            "file", detail=f"exceeds {payload_limit // (1024 * 1024)}MB", name=url
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

        type_name = out_ext.lstrip(".")
        header = f"[URL: {url} | status: 200 | type: {type_name}]"
        from tools.base import truncate_output

        body = truncate_output(text_content, tool_name="web_fetch", ext=out_ext)
        plain_content = f"{header}\n\n{body}"
        return ToolResult.done(content=plain_content, display="")

