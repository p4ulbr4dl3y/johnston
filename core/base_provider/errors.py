import ast
import json
import re
from typing import Optional


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
