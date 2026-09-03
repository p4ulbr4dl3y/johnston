import ast
import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from core.domain.policies.messages import (
    SYSTEM_NOTICE_KIND_IMAGES_OMITTED,
    _xml_escape,
    format_system_note,
)
from core.infrastructure.adapters.base import extract_image_payload


def _extract_error_fields(data: dict) -> tuple[str, str]:
    """Extract ``(message, type/code)`` from an ``{"error": ...}`` payload.

    Handles the nested ``{"error": {"error": {...}}}`` forms used by Anthropic
    and OpenAI-compatible providers; returns ``("", "")`` when nothing matches.
    """
    err_obj = data.get("error")
    if isinstance(err_obj, dict):
        inner_err = err_obj.get("error")
        if isinstance(inner_err, dict):
            return inner_err.get("message") or "", inner_err.get("type") or inner_err.get("code") or ""
        return err_obj.get("message") or "", err_obj.get("type") or err_obj.get("code") or ""
    if isinstance(err_obj, str):
        return err_obj, ""
    if "message" in data:
        return data["message"], ""
    return "", ""


_HTTP_STATUS_PHRASES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    408: "Request Timeout",
    429: "Rate limit exceeded",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def format_api_error(err: Exception) -> str:
    """Formats API exceptions into a clean, unified Markdown string.

    Parses OpenAI APIErrors, HTTPStatusErrors, and raw JSON dicts across
    OpenAI/OpenCode, Anthropic, Gemini, and Ollama formats.
    """
    if err is None:
        return "**API Error:** `Unknown error`"

    status_code: Optional[int] = getattr(err, "status_code", None)
    if status_code is None and hasattr(err, "response") and getattr(err, "response", None) is not None:
        status_code = getattr(err.response, "status_code", None)

    msg = ""
    err_type = ""

    body = getattr(err, "body", None)
    if isinstance(body, dict):
        msg, err_type = _extract_error_fields(body)

    raw_str = str(err).strip()
    if not msg:
        dict_match = re.search(r"(\{.*\})", raw_str, re.DOTALL)
        if dict_match:
            try:
                raw_dict = dict_match.group(1)
                try:
                    parsed_data = json.loads(raw_dict)
                except Exception:
                    parsed_data = ast.literal_eval(raw_dict)
                if isinstance(parsed_data, dict):
                    msg, err_type = _extract_error_fields(parsed_data)
            except Exception:
                pass

    if not msg:
        if hasattr(err, "message") and isinstance(getattr(err, "message"), str) and getattr(err, "message"):
            msg = getattr(err, "message")
        else:
            msg = re.sub(r"^Error code:\s*\d+\s*-\s*", "", raw_str)

    if not status_code:
        status_match = re.search(r"\b(4\d\d|5\d\d)\b", raw_str)
        if status_match:
            try:
                status_code = int(status_match.group(1))
            except ValueError:
                pass

    msg = msg.strip("'\" \n\r\t")
    if status_code:
        msg = re.sub(
            rf"^(HTTP\s*{status_code}[:\s]*|Error code:\s*{status_code}\s*-\s*|{status_code}\s*[:\-]\s*)",
            "",
            msg,
            flags=re.IGNORECASE,
        ).strip()
    msg = re.sub(r"^HTTP\s*\d+[:\s]*", "", msg, flags=re.IGNORECASE).strip()
    msg = msg.rstrip(":").strip()

    if not msg and status_code:
        msg = _HTTP_STATUS_PHRASES.get(status_code, "HTTP error")

    tag_parts = []
    if status_code:
        tag_parts.append(str(status_code))
    if err_type and str(err_type) != str(status_code):
        tag_parts.append(str(err_type))

    if tag_parts:
        header = f"**API Error ({' '.join(tag_parts)}):**"
    else:
        header = "**API Error:**"

    return f"{header} `{msg}`" if msg else f"{header} `Unknown error`"


class ErrorHandlingMixin:
    """Mixin providing retry-classification and vision-error handling for BaseAgent."""

    def _extract_retry_after(self, err: Exception) -> Optional[float]:
        """Extracts suggested retry delay in seconds from response headers or error context."""
        if err is None:
            return None
        try:
            response = getattr(err, "response", None)
            headers = getattr(response, "headers", None) if response is not None else None
            if headers is not None:
                if "retry-after-ms" in headers:
                    val = float(headers["retry-after-ms"])
                    if val > 0:
                        return val / 1000.0
                if "retry-after" in headers:
                    val = float(headers["retry-after"])
                    if val > 0:
                        return val
        except (ValueError, TypeError):
            pass
        return None

    def _is_retryable_error(self, err: Exception) -> bool:
        if err is None:
            return False

        err_str = str(err).lower()

        # 1. HTTP status code check
        status_code: Optional[int] = getattr(err, "status_code", None)
        if status_code is None and hasattr(err, "response") and getattr(err, "response", None) is not None:
            status_code = getattr(err.response, "status_code", None)

        if status_code in (400, 401, 403, 404, 422):
            return False

        # 2. Non-retryable error terms
        non_retryable_terms = [
            "invalid api key",
            "unauthorized",
            "authentication",
            "invalid_api_key",
            "context_length_exceeded",
            "context window",
            "maximum context length",
            "invalid request",
            "model_not_found",
            "permission_denied",
            "account_deactivated",
            "billing_not_active",
        ]
        if any(term in err_str for term in non_retryable_terms):
            return False

        # 3. Explicit retryable HTTP status codes (e.g. 429, 5xx, 529 overloaded)
        if status_code in (408, 429, 500, 502, 503, 504, 524, 529):
            return True

        # 4. Asyncio / Runtime timeout errors
        if isinstance(err, (asyncio.TimeoutError, RuntimeError)):
            if "timeout" in err_str or isinstance(err, asyncio.TimeoutError):
                return True

        # 5. HTTPX exception types
        try:
            import httpx

            if isinstance(err, (httpx.TimeoutException, httpx.NetworkError)):
                return True
            if isinstance(err, httpx.HTTPStatusError):
                if err.response.status_code in (401, 400, 403, 404, 422):
                    return False
                return True
        except ImportError:
            pass

        # 6. Fallback retryable terms
        retryable_terms = [
            "timeout",
            "timed out",
            "rate limit",
            "429",
            "500",
            "502",
            "503",
            "504",
            "524",
            "529",
            "connection",
            "network",
            "server error",
            "reset",
            "refused",
            "overloaded",
            "chunk timeout",
            "service unavailable",
            "gateway timeout",
        ]
        if any(term in err_str for term in retryable_terms):
            return True

        return False

    def _is_vision_error(self, err: Exception) -> bool:
        if err is None:
            return False
        err_str = str(err).lower()
        vision_keywords = [
            "image input",
            "does not support image",
            "image_url",
            "multimodal",
            "vision",
            "unsupported image",
            "no endpoints found that support image",
            "image input not supported",
        ]
        return any(kw in err_str for kw in vision_keywords)

    def _sanitize_vision_error_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sanitizes system history when non-vision model handles previous image context.
        Prevents API errors by replacing raw image tool payloads with clear refusal text.
        """
        if not messages:
            return messages

        sanitized = []
        for msg in messages:
            if not isinstance(msg, dict):
                sanitized.append(msg)
                continue

            role = msg.get("role")
            content = msg.get("content")

            if role == "user" and isinstance(content, list):
                has_image = any(
                    isinstance(item, dict) and item.get("type") in ("image_url", "image") for item in content
                )
                if has_image:
                    text_parts = [
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
                    ]
                    # Escape the user-supplied text before concatenating with
                    # the synthetic system_note. Without this, a malicious or
                    # careless user message containing literal
                    # `</system_note><system_note kind="...">...` would
                    # truncate our wrapper and inject a fake system_note that
                    # the model would treat as authoritative.
                    clean_text = "\n".join(_xml_escape(p) for p in text_parts).strip()
                    # Structured system_note with kind + reason attrs. The
                    # model sees WHY images are gone (model lacks vision)
                    # and WHAT to do (don't retry, tell the user). Prevents
                    # endless image-resend loops when a user attaches to a
                    # non-vision-capable session.
                    note = format_system_note(
                        kind=SYSTEM_NOTICE_KIND_IMAGES_OMITTED,
                        body="Attached images were stripped: the active model does not support vision. "
                             "Do not attempt to re-attach or re-send the same image; tell the user you "
                             "cannot view it and ask them to describe the content in text.",
                        reason="vision_unsupported",
                    )
                    combined_text = f"{clean_text}\n{note}".strip() if clean_text else note
                    sanitized.append({"role": "user", "content": combined_text})
                    continue

            if role == "tool":
                is_img = False
                img_path = "image"
                parsed_img = extract_image_payload(content)
                if parsed_img:
                    is_img = True
                    img_path = parsed_img.get("path", "image")
                elif isinstance(content, str) and ('"type": "image"' in content or "<image " in content or "[Image file:" in content):
                    is_img = True
                    path_match = re.search(r"['\"]path['\"]\s*:\s*['\"]([^'\"]+)['\"]", content)
                    if path_match:
                        img_path = path_match.group(1)

                if is_img:
                    from core.domain.defaults.errors import format_tool_error

                    msg_copy = dict(msg)
                    msg_copy["content"] = format_tool_error(
                        "vision_unsupported",
                        name=img_path,
                        detail="You do not support vision. Tell user you cannot view images. Do not retry.",
                    )
                    sanitized.append(msg_copy)
                    continue

            sanitized.append(msg)
        return sanitized
