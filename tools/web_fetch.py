import asyncio
import os
import tempfile
from typing import Any, Dict, List

import httpx

from tools.base import BaseTool, truncate_output

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Johnston/0.1"
)

MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB limit


def _convert_content_to_md_sync(content_bytes: bytes, suffix: str = ".html") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content_bytes)
        tmp_path = tmp.name

    try:
        from tools.read import convert_doc_to_markdown_sync
        return convert_doc_to_markdown_sync(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch content from a web URL. Automatically converts HTML/PDF/DOCX to Markdown cleanly. Specify url, and optionally raw, start_line, end_line."
    schema = {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                    "raw": {"type": "boolean", "description": "If true, skip Markdown conversion and return raw response text"},
                    "start_line": {"type": "integer", "description": "Start line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line number (inclusive)"}
                },
                "required": ["url"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        self._ensure_context(app)
        url = args.get("url", "").strip()
        if not url:
            return "Error: parameter 'url' is required."

        if not (url.startswith("http://") or url.startswith("https://")):
            return f"Error: invalid URL scheme for '{url}'. Must start with http:// or https://."

        raw_mode = bool(args.get("raw", False))

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        content_bytes = b""
        content_type = ""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    # Pre-check Content-Length to fail fast on oversized responses.
                    cl = response.headers.get("content-length")
                    if cl:
                        try:
                            if int(cl) > MAX_RESPONSE_SIZE:
                                return f"Error: response body for '{url}' exceeds max allowed size of {MAX_RESPONSE_SIZE // (1024*1024)}MB."
                        except ValueError:
                            pass
                    # Stream the body with a hard cap so an oversized or chunked
                    # response cannot exhaust memory before the size check can trigger.
                    total = 0
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_RESPONSE_SIZE:
                            return f"Error: response body for '{url}' exceeds max allowed size of {MAX_RESPONSE_SIZE // (1024*1024)}MB."
                        chunks.append(chunk)
                    content_bytes = b"".join(chunks)
        except httpx.HTTPStatusError as e:
            return f"Error fetching '{url}': HTTP {e.response.status_code} {e.response.reason_phrase}"
        except httpx.TimeoutException:
            return f"Error fetching '{url}': Request timed out after 20 seconds."
        except Exception as e:
            return f"Error fetching '{url}': {e}"

        lines: List[str] = []

        if raw_mode:
            text_content = content_bytes.decode("utf-8", errors="replace")
            lines = text_content.splitlines(keepends=True)
        else:
            if "application/pdf" in content_type or url.lower().endswith(".pdf"):
                suffix = ".pdf"
            elif "application/vnd.openxmlformats-officedocument.wordprocessingml" in content_type or url.lower().endswith(".docx"):
                suffix = ".docx"
            elif "application/vnd.openxmlformats-officedocument.spreadsheetml" in content_type or url.lower().endswith(".xlsx"):
                suffix = ".xlsx"
            else:
                suffix = ".html"

            if "json" in content_type or "text/plain" in content_type:
                text_content = content_bytes.decode("utf-8", errors="replace")
                lines = text_content.splitlines(keepends=True)
            else:
                try:
                    md_text = await asyncio.to_thread(_convert_content_to_md_sync, content_bytes, suffix)
                    lines = md_text.splitlines(keepends=True)
                except Exception:
                    text_content = content_bytes.decode("utf-8", errors="replace")
                    lines = text_content.splitlines(keepends=True)

        start = args.get("start_line")
        end = args.get("end_line")

        def _fmt_line(idx: int, line_str: str) -> str:
            if not line_str.endswith("\n"):
                line_str = line_str + "\n"
            return f"{idx:5d} | {line_str}"

        if start is not None or end is not None:
            s_idx = max(0, (start or 1) - 1)
            e_idx = end if end is not None else len(lines)
            sliced = lines[s_idx:e_idx]
            formatted_lines = [_fmt_line(s_idx + i + 1, line) for i, line in enumerate(sliced)]
            content = "".join(formatted_lines)
            return f"=== Lines {s_idx+1}-{min(e_idx, len(lines))} of {len(lines)} in {url} ===\n{content}"

        formatted_lines = [_fmt_line(i + 1, line) for i, line in enumerate(lines)]
        content = "".join(formatted_lines)
        return truncate_output(content, max_chars=8000, hint=f"URL output has {len(lines)} lines. Use start_line/end_line to read specific ranges.")
