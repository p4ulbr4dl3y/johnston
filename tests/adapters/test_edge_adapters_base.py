"""Edge-case tests for core.adapters.base helpers.

Focus on robustness of shared helpers rather than provider wire parsing.
All pure functions; network-level helpers use mocks.
"""
import json

import pytest

from core.adapters.base import (
    ImageDetails,
    build_adapter_usage_event,
    check_httpx_response_status,
    extract_image_details,
    extract_image_payload,
    normalize_tool_arguments_str,
    parse_sse_line,
    parse_tool_call_args,
    sort_keys_recursive,
)


# --------------------------------------------------------------------------- #
# sort_keys_recursive
# --------------------------------------------------------------------------- #
class TestSortKeysRecursive:
    def test_none_returns_none(self):
        # sort_keys_recursive should not crash on None / primitives
        assert sort_keys_recursive(None) is None
        assert sort_keys_recursive(42) == 42
        assert sort_keys_recursive("x") == "x"

    def test_unicode_keys_sorted(self):
        obj = {"\U0001F600": 1, "a": 2, "z": 3}
        res = sort_keys_recursive(obj)
        assert list(res.keys()) == ["a", "z", "\U0001F600"]

    def test_mixed_nested(self):
        res = sort_keys_recursive({"b": [3, 2, {"d": 1, "c": 0}], "a": 1})
        assert list(res["b"][2].keys()) == ["c", "d"]

    def test_dict_with_non_comparable_keys(self):
        # keys of different runtime types must still sort deterministically
        obj = {1: "int", "a": "str"}
        res = sort_keys_recursive(obj)
        assert set(res.keys()) == {1, "a"}
        # Deterministic ordering: sorted by (typename, str) -> ints before strs.
        assert list(res.keys()) == [1, "a"]


# --------------------------------------------------------------------------- #
# parse_tool_call_args
# --------------------------------------------------------------------------- #
class TestParseToolCallArgs:
    def test_none_produces_empty(self):
        assert parse_tool_call_args(None) == ("", {})

    def test_non_dict_payload(self):
        assert parse_tool_call_args("not a dict") == ("", {})
        assert parse_tool_call_args([1, 2]) == ("", {})

    def test_no_function_key(self):
        assert parse_tool_call_args({"id": "c1"}) == ("", {})

    def test_function_not_a_dict(self):
        assert parse_tool_call_args({"function": "string"}) == ("", {})

    def test_missing_name_and_arguments(self):
        assert parse_tool_call_args({"function": {}}) == ("", {})

    def test_invalid_json_arguments_fallback_empty(self):
        name, args = parse_tool_call_args({"function": {"name": "run", "arguments": "{not json"}})
        assert name == "run"
        assert args == {}

    def test_empty_string_arguments(self):
        _, args = parse_tool_call_args({"function": {"name": "run", "arguments": ""}})
        assert args == {}

    def test_whitespace_arguments(self):
        _, args = parse_tool_call_args({"function": {"name": "run", "arguments": "   "}})
        assert args == {}

    def test_json_null_arguments(self):
        _, args = parse_tool_call_args({"function": {"name": "run", "arguments": "null"}})
        assert args is None  # json.loads("null") -> None; helper passes through

    def test_dict_arguments_passthrough(self):
        name, args = parse_tool_call_args({"function": {"name": "run", "arguments": {"cmd": "ls"}}})
        assert name == "run"
        assert args == {"cmd": "ls"}

    def test_none_arguments_default_empty(self):
        _, args = parse_tool_call_args({"function": {"name": "run", "arguments": None}})
        assert args == {}


# --------------------------------------------------------------------------- #
# extract_image_payload / extract_image_details
# --------------------------------------------------------------------------- #
class TestExtractImage:
    def test_none_input(self):
        assert extract_image_payload(None) is None
        assert extract_image_details(None) is None

    def test_non_image_dict(self):
        assert extract_image_payload({"type": "text", "text": "hi"}) is None

    def test_image_dict_no_base64(self):
        assert extract_image_payload({"type": "image", "path": "x.png"}) is not None
        assert extract_image_details({"type": "image", "path": "x.png"}) is None

    def test_image_details_defaults(self):
        res = extract_image_details({"type": "image", "base64": "QUFB"})
        assert res == ImageDetails("[Image content]", "image/jpeg", "QUFB", "high")

    def test_image_details_custom(self):
        res = extract_image_details(
            {"type": "image", "base64": "QUFB", "summary": "pic", "media_type": "image/png", "detail": "low"}
        )
        assert (res.summary, res.media_type, res.base64) == ("pic", "image/png", "QUFB")
        assert res.detail == "low"

    def test_str_image_payload(self):
        payload = json.dumps({"type": "image", "base64": "QUFB", "media_type": "image/jpeg"})
        assert extract_image_details(payload) == ImageDetails("[Image content]", "image/jpeg", "QUFB", "high")

    def test_malformed_str_image_payload(self):
        assert extract_image_payload('{"type": "image"') is None

    def test_unicode_base64_roundtrip(self):
        res = extract_image_details({"type": "image", "base64": "8J+ZgSB0ZXN0", "summary": "фото 😀"})
        assert res.summary == "фото 😀"


# --------------------------------------------------------------------------- #
# build_adapter_usage_event
# --------------------------------------------------------------------------- #
class TestBuildAdapterUsageEvent:
    def test_defaults(self):
        etype, evt = build_adapter_usage_event()
        assert etype == "adapter_usage"
        assert evt == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0}

    def test_with_total(self):
        _, evt = build_adapter_usage_event(10, 5, total_tokens=100)
        assert evt["total_tokens"] == 100

    def test_computed_total(self):
        _, evt = build_adapter_usage_event(10, 5)
        assert evt["total_tokens"] == 15

    def test_str_numbers_coerced(self):
        _, evt = build_adapter_usage_event("10", "5")
        assert evt["prompt_tokens"] == 10
        assert evt["completion_tokens"] == 5
        assert evt["total_tokens"] == 15

    def test_none_completion_defaults_zero(self):
        _, evt = build_adapter_usage_event(10, None)
        assert evt["completion_tokens"] == 0

    def test_nan_prompt_tokens_crashes(self):
        # Fixed: NaN no longer raises; coerced to 0.
        ev, usage = build_adapter_usage_event(float("nan"), 5)
        assert ev == "adapter_usage"
        assert usage["prompt_tokens"] == 0

    def test_inf_total_tokens_crashes(self):
        # Fixed: Inf no longer raises; coerced to 0.
        _, usage = build_adapter_usage_event(10, 5, total_tokens=float("inf"))
        assert usage["total_tokens"] == 0

    def test_nan_completion_crashes(self):
        # Fixed: NaN no longer raises; coerced to 0.
        _, usage = build_adapter_usage_event(10, float("nan"))
        assert usage["completion_tokens"] == 0


# --------------------------------------------------------------------------- #
# normalize_tool_arguments_str
# --------------------------------------------------------------------------- #
class TestNormalizeToolArgumentsStr:
    def test_none_to_empty_json(self):
        assert normalize_tool_arguments_str(None) == "{}"

    def test_dict_to_json(self):
        assert normalize_tool_arguments_str({"cmd": "ls"}) == '{"cmd": "ls"}'

    def test_dict_unicode_ensure_ascii_false(self):
        assert normalize_tool_arguments_str({"msg": "привет"}) == '{"msg": "привет"}'

    def test_empty_dict(self):
        assert normalize_tool_arguments_str({}) == "{}"

    def test_passthrough_string(self):
        assert normalize_tool_arguments_str('{"a": 1}') == '{"a": 1}'

    def test_empty_string(self):
        assert normalize_tool_arguments_str("") == "{}"

    def test_list_converted(self):
        assert normalize_tool_arguments_str([1, 2]) == "[1, 2]"

    def test_emojis_preserved(self):
        assert normalize_tool_arguments_str({"e": "🔥"}) == '{"e": "🔥"}'


# --------------------------------------------------------------------------- #
# parse_sse_line
# --------------------------------------------------------------------------- #
class TestParseSseLine:
    def test_empty_line(self):
        assert parse_sse_line("") is None

    def test_non_data_line(self):
        assert parse_sse_line("event: message") is None

    def test_data_done_sentinel(self):
        assert parse_sse_line("data: [DONE]") is None

    def test_data_empty(self):
        assert parse_sse_line("data:   ") is None

    def test_valid_json(self):
        assert parse_sse_line('data: {"a": 1}') == {"a": 1}

    def test_invalid_json_returns_none(self):
        assert parse_sse_line("data: {not json") is None

    def test_data_colon_in_value(self):
        assert parse_sse_line('data: {"url": "http://x"}') == {"url": "http://x"}

    def test_lowercase_data_not_parsed(self):
        # SSE spec requires exact 'data:' prefix
        assert parse_sse_line('Data: {"a": 1}') is None

    def test_json_null_returns_none_payload(self):
        # json NULL still returns a value; consumer must guard
        assert parse_sse_line("data: null") is None


# --------------------------------------------------------------------------- #
# check_httpx_response_status
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, status_code=200, body=b"", request=None):
        self.status_code = status_code
        self._body = body
        self.request = request

    async def aread(self):
        return self._body


class TestCheckHttpxResponseStatus:
    async def test_ok_200_no_raise(self):
        await check_httpx_response_status(_FakeResp(200))

    async def test_ok_3xx_no_raise(self):
        # 3xx treated as success by the helper (only >=400 raises)
        await check_httpx_response_status(_FakeResp(302))

    @pytest.mark.parametrize("code", [400, 401, 404, 429, 500, 502, 503])
    async def test_raises_on_error_codes(self, code):
        import httpx

        with pytest.raises(httpx.HTTPStatusError):
            await check_httpx_response_status(
                _FakeResp(code, b"oops", request=object())
            )

    async def test_error_body_in_message(self):
        import httpx

        with pytest.raises(httpx.HTTPStatusError) as exc:
            await check_httpx_response_status(_FakeResp(500, b"internal boom", request=object()))
        assert "internal boom" in str(exc.value)

    async def test_unicode_error_body(self):
        import httpx

        with pytest.raises(httpx.HTTPStatusError) as exc:
            await check_httpx_response_status(_FakeResp(429, "слишком много".encode("utf-8"), request=object()))
        assert "слишком много" in str(exc.value)

    async def test_none_status_code_defaults_success(self):
        # missing status_code attr treated as 200 (no raise)
        await check_httpx_response_status(object())
