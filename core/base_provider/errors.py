import ast
import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from core.infrastructure.adapters.base import extract_image_payload


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
        err_obj = body.get("error")
        if isinstance(err_obj, dict):
            inner_err = err_obj.get("error")
            if isinstance(inner_err, dict):
                msg = inner_err.get("message") or ""
                err_type = inner_err.get("type") or inner_err.get("code") or ""
            else:
                msg = err_obj.get("message") or ""
                err_type = err_obj.get("type") or err_obj.get("code") or ""
        elif isinstance(err_obj, str):
            msg = err_obj
        elif "message" in body:
            msg = body["message"]

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
                    err_obj = parsed_data.get("error")
                    if isinstance(err_obj, dict):
                        inner_err = err_obj.get("error")
                        if isinstance(inner_err, dict):
                            msg = inner_err.get("message") or ""
                            err_type = inner_err.get("type") or inner_err.get("code") or ""
                        else:
                            msg = err_obj.get("message") or ""
                            err_type = err_obj.get("type") or err_obj.get("code") or ""
                    elif isinstance(err_obj, str):
                        msg = err_obj
                    elif "message" in parsed_data:
                        msg = parsed_data["message"]
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

        # 3. Known non-retryable OpenAI exception types
        try:
            import openai

            if isinstance(
                err,
                (
                    openai.AuthenticationError,
                    openai.PermissionDeniedError,
                    openai.BadRequestError,
                    openai.NotFoundError,
                ),
            ):
                return False
        except ImportError:
            pass

        # 4. Explicit retryable HTTP status codes (e.g. 429, 5xx, 529 overloaded)
        if status_code in (408, 429, 500, 502, 503, 504, 524, 529):
            return True

        # 5. Asyncio / Runtime timeout errors
        if isinstance(err, (asyncio.TimeoutError, RuntimeError)):
            if "timeout" in err_str or isinstance(err, asyncio.TimeoutError):
                return True

        # 6. HTTPX exception types
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

        # 7. OpenAI retryable exception types
        try:
            import openai

            if isinstance(
                err,
                (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError, openai.RateLimitError),
            ):
                return True
        except ImportError:
            pass

        # 8. Fallback retryable terms
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
                has_image_url = any(isinstance(item, dict) and item.get("type") == "image_url" for item in content)
                if has_image_url:
                    continue

            if role == "tool":
                is_img = False
                img_path = "image"
                parsed_img = extract_image_payload(content)
                if parsed_img:
                    is_img = True
                    img_path = parsed_img.get("path", "image")
                elif isinstance(content, str) and ('"type": "image"' in content or "[Image file:" in content):
                    is_img = True
                    path_match = re.search(r"['\"]path['\"]\s*:\s*['\"]([^'\"]+)['\"]", content)
                    if path_match:
                        img_path = path_match.group(1)

                if is_img:
                    msg_copy = dict(msg)
                    msg_copy["content"] = (
                        f"ERR: cannot read image '{img_path}' [Hint: You do not support vision. Tell user you cannot view images. Do not retry.]"
                    )
                    sanitized.append(msg_copy)
                    continue

            sanitized.append(msg)
        return sanitized
