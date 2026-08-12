import ipaddress
import os
import re
import socket
import tempfile
import threading
from typing import Any, Dict

import httpx

from tools.base import BaseTool, format_tool_error, truncate_output
from tools.cancel import run_cancellable

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Johnston/0.1"
)

MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB limit


def _is_private_host(url: str) -> bool:
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
        infos = socket.getaddrinfo(host, None)
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


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a URL. Converts HTML/PDF/DOCX to Markdown. raw returns raw text."

    schema = {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "raw": {"type": "boolean", "description": "Skip Markdown conversion, return raw response"},
                },
                "required": ["url"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        url = (args.get("url") or "").strip()
        if not url:
            return format_tool_error("params", name="url", detail="required")

        if not (url.startswith("http://") or url.startswith("https://")):
            return format_tool_error("scheme", name=url, detail="must be http(s)")

        if _is_private_host(url):
            return format_tool_error("blocked", name=url, detail="private/loopback address is not allowed")

        raw_mode = bool(args.get("raw", False))

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        async def _guard_request(req: "httpx.Request") -> None:
            if _is_private_host(str(req.url)):
                raise httpx.RequestError("private/loopback redirect target is not allowed", request=req)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20.0, event_hooks={"request": [_guard_request]}
            ) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    # Pre-check Content-Length to fail fast on oversized responses.
                    cl = response.headers.get("content-length")
                    if cl:
                        try:
                            if int(cl) > MAX_RESPONSE_SIZE:
                                return format_tool_error(
                                    "file", detail=f"exceeds {MAX_RESPONSE_SIZE // (1024 * 1024)}MB", name=url
                                )
                        except ValueError:
                            pass
                    # Stream the body with a hard cap so an oversized or chunked
                    # response cannot exhaust memory before the size check can trigger.
                    total = 0
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_RESPONSE_SIZE:
                            return format_tool_error(
                                "file", detail=f"exceeds {MAX_RESPONSE_SIZE // (1024 * 1024)}MB", name=url
                            )
                        chunks.append(chunk)
                    content_bytes = b"".join(chunks)
        except httpx.HTTPStatusError as e:
            return format_tool_error("http", detail=f"{e.response.status_code} {e.response.reason_phrase}", name=url)
        except httpx.TimeoutException:
            return format_tool_error("timeout", name=url)
        except Exception as e:
            return format_tool_error("fetch", detail=str(e), name=url)

        if raw_mode:
            text_content = _sanitize_web_content(content_bytes.decode("utf-8", errors="replace"))
        else:
            if "application/pdf" in content_type or url.lower().endswith(".pdf"):
                suffix = ".pdf"
            elif (
                "application/vnd.openxmlformats-officedocument.wordprocessingml" in content_type
                or url.lower().endswith(".docx")
            ):
                suffix = ".docx"
            elif "application/vnd.openxmlformats-officedocument.spreadsheetml" in content_type or url.lower().endswith(
                ".xlsx"
            ):
                suffix = ".xlsx"
            else:
                suffix = ".html"

            if "json" in content_type or "text/plain" in content_type:
                text_content = _sanitize_web_content(content_bytes.decode("utf-8", errors="replace"))
            else:
                try:
                    text_content = await run_cancellable(_convert_content_to_md_sync, content_bytes, suffix)
                    text_content = _sanitize_web_content(text_content)
                except Exception:
                    text_content = _sanitize_web_content(content_bytes.decode("utf-8", errors="replace"))

        return truncate_output(
            text_content,
            max_chars=8000,
            tool_name="web_fetch",
        )
