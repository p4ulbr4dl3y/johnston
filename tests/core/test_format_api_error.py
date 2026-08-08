import asyncio
import sys
import unittest
from unittest import mock

import httpx

from core.base_provider import format_api_error
from core.base_provider.errors import ErrorHandlingMixin


class TestFormatApiError(unittest.TestCase):
    def test_opencode_upstream_error(self):
        err = Exception("Error code: 401 - {'type': 'error', 'error': {'type': 'AuthError', 'message': 'Request blocked by upstream provider.'}}")
        res = format_api_error(err)
        self.assertEqual(res, "**API Error (401 AuthError):** `Request blocked by upstream provider.`")

    def test_openai_standard_error(self):
        class MockOpenAIError(Exception):
            status_code = 401
            body = {
                "error": {
                    "message": "Incorrect API key provided",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key"
                }
            }

        res = format_api_error(MockOpenAIError())
        self.assertEqual(res, "**API Error (401 invalid_request_error):** `Incorrect API key provided`")

    def test_anthropic_error(self):
        class MockAnthropicError(Exception):
            status_code = 403
            body = {
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "invalid x-api-key"
                }
            }

        res = format_api_error(MockAnthropicError())
        self.assertEqual(res, "**API Error (403 authentication_error):** `invalid x-api-key`")

    def test_gemini_error(self):
        class MockGeminiError(Exception):
            status_code = 400
            body = {
                "error": {
                    "code": 400,
                    "message": "API key not valid",
                    "status": "INVALID_ARGUMENT"
                }
            }

        res = format_api_error(MockGeminiError())
        self.assertEqual(res, "**API Error (400):** `API key not valid`")

    def test_ollama_error(self):
        err = Exception('{"error": "model \'llama3\' not found"}')
        res = format_api_error(err)
        self.assertEqual(res, "**API Error:** `model 'llama3' not found`")

    def test_simple_string_error(self):
        err = RuntimeError("Connection timeout")
        res = format_api_error(err)
        self.assertEqual(res, "**API Error:** `Connection timeout`")


class TestFormatApiErrorBranches(unittest.TestCase):
    def test_none_error(self):
        res = format_api_error(None)
        self.assertEqual(res, "**API Error:** `Unknown error`")

    def test_empty_exception(self):
        res = format_api_error(Exception())
        self.assertEqual(res, "**API Error:** `Unknown error`")

    def test_status_code_from_response(self):
        class MockError(Exception):
            response = mock.MagicMock(status_code=429)

        res = format_api_error(MockError("Server overloaded"))
        self.assertEqual(res, "**API Error (429):** `Server overloaded`")

    def test_body_nested_error_dict(self):
        class MockError(Exception):
            status_code = 400
            body = {"error": {"error": {"message": "inner message", "type": "inner_type"}}}

        res = format_api_error(MockError())
        self.assertEqual(res, "**API Error (400 inner_type):** `inner message`")

    def test_body_error_string(self):
        class MockError(Exception):
            status_code = 400
            body = {"error": "plain error string"}

        res = format_api_error(MockError())
        self.assertEqual(res, "**API Error (400):** `plain error string`")

    def test_body_message_key(self):
        class MockError(Exception):
            status_code = 500
            body = {"message": "server exploded"}

        res = format_api_error(MockError())
        self.assertEqual(res, "**API Error (500):** `server exploded`")

    def test_raw_str_nested_error_dict(self):
        err = Exception('{"error": {"error": {"message": "deep message", "type": "deep"}}}')
        res = format_api_error(err)
        self.assertEqual(res, "**API Error (deep):** `deep message`")

    def test_raw_str_message_key(self):
        err = Exception('{"message": "raw message"}')
        res = format_api_error(err)
        self.assertEqual(res, "**API Error:** `raw message`")

    def test_raw_str_ast_literal_eval(self):
        err = Exception("{'error': 'single quoted message'}")
        res = format_api_error(err)
        self.assertEqual(res, "**API Error:** `single quoted message`")

    def test_raw_str_parse_failure(self):
        err = Exception("Some error {not valid json or literal}")
        res = format_api_error(err)
        self.assertEqual(res, "**API Error:** `Some error {not valid json or literal}`")

    def test_message_attribute(self):
        class MockError(Exception):
            message = "custom message attribute"

        res = format_api_error(MockError())
        self.assertEqual(res, "**API Error:** `custom message attribute`")


class _FakeAPIError(Exception):
    """Stand-in for openai exception classes when faking the openai module."""


_OPENAI_ERROR_ATTRS = (
    "AuthenticationError",
    "PermissionDeniedError",
    "BadRequestError",
    "NotFoundError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
)


def _fake_openai_module(**overrides):
    module = type("FakeOpenAI", (), {})()
    for name in _OPENAI_ERROR_ATTRS:
        setattr(module, name, _FakeAPIError)
    for name, cls in overrides.items():
        setattr(module, name, cls)
    return module


class TestErrorHandlingMixin(unittest.TestCase):
    def setUp(self):
        self.mixin = ErrorHandlingMixin()

    def test_retryable_none(self):
        self.assertFalse(self.mixin._is_retryable_error(None))

    def test_retryable_status_code_from_response(self):
        class MockError(Exception):
            response = mock.MagicMock(status_code=503)

        self.assertTrue(self.mixin._is_retryable_error(MockError("unavailable")))

    def test_retryable_non_retryable_status_code(self):
        class MockError(Exception):
            status_code = 404

        self.assertFalse(self.mixin._is_retryable_error(MockError("not found")))

    def test_retryable_non_retryable_terms(self):
        self.assertFalse(self.mixin._is_retryable_error(Exception("Invalid API key provided")))

    def test_retryable_openai_non_retryable_types(self):
        class FakeAuthError(Exception):
            pass

        openai_mod = _fake_openai_module(AuthenticationError=FakeAuthError)
        with mock.patch.dict(sys.modules, {"openai": openai_mod}):
            self.assertFalse(self.mixin._is_retryable_error(FakeAuthError("denied by upstream")))

    def test_retryable_openai_import_error(self):
        with mock.patch.dict(sys.modules, {"openai": None}):
            self.assertFalse(self.mixin._is_retryable_error(Exception("generic failure")))

    def test_retryable_retryable_status_code(self):
        class MockError(Exception):
            status_code = 429

        self.assertTrue(self.mixin._is_retryable_error(MockError("rate limited")))

    def test_retryable_asyncio_timeout(self):
        self.assertTrue(self.mixin._is_retryable_error(asyncio.TimeoutError()))

    def test_retryable_runtime_error_timeout(self):
        self.assertTrue(self.mixin._is_retryable_error(RuntimeError("request timed out")))

    def test_retryable_httpx_timeout(self):
        self.assertTrue(self.mixin._is_retryable_error(httpx.TimeoutException("slow response")))

    def test_retryable_httpx_network_error(self):
        self.assertTrue(self.mixin._is_retryable_error(httpx.NetworkError("connection refused")))

    def test_retryable_httpx_status_error_retryable(self):
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(451, request=request)
        err = httpx.HTTPStatusError("Client error '451'", request=request, response=response)
        self.assertTrue(self.mixin._is_retryable_error(err))

    def test_retryable_httpx_status_error_non_retryable_response(self):
        class MockStatusError(httpx.HTTPStatusError):
            status_code = 418

        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(400, request=request)
        err = MockStatusError("Client error '400 Bad Request'", request=request, response=response)
        self.assertFalse(self.mixin._is_retryable_error(err))

    def test_retryable_httpx_import_error(self):
        with mock.patch.dict(sys.modules, {"httpx": None}):
            self.assertFalse(self.mixin._is_retryable_error(Exception("generic failure")))

    def test_retryable_openai_retryable_types(self):
        class FakeRateLimitError(Exception):
            pass

        openai_mod = _fake_openai_module(RateLimitError=FakeRateLimitError)
        with mock.patch.dict(sys.modules, {"openai": openai_mod}):
            self.assertTrue(self.mixin._is_retryable_error(FakeRateLimitError("server overloaded")))

    def test_retryable_fallback_terms(self):
        self.assertTrue(self.mixin._is_retryable_error(Exception("connection reset by peer")))

    def test_vision_error_none(self):
        self.assertFalse(self.mixin._is_vision_error(None))

    def test_vision_error_keyword_hit(self):
        self.assertTrue(self.mixin._is_vision_error(Exception("model does not support image input")))

    def test_vision_error_no_keyword(self):
        self.assertFalse(self.mixin._is_vision_error(Exception("plain error message")))

    def test_sanitize_non_dict_messages(self):
        messages = ["plain string", 42, None]
        self.assertEqual(self.mixin._sanitize_vision_error_messages(messages), messages)

    def test_sanitize_user_image_url_skipped(self):
        messages = [{"role": "user", "content": [{"type": "image_url", "url": "..."}]}]
        self.assertEqual(self.mixin._sanitize_vision_error_messages(messages), [])

    def test_sanitize_user_without_image_kept(self):
        messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        self.assertEqual(self.mixin._sanitize_vision_error_messages(messages), messages)

    def test_sanitize_tool_image_dict(self):
        messages = [{"role": "tool", "content": {"type": "image", "path": "/tmp/a.png"}}]
        result = self.mixin._sanitize_vision_error_messages(messages)
        self.assertEqual(
            result[0]["content"],
            "ERR: cannot read image '/tmp/a.png' [Hint: You do not support vision. Tell user you cannot view images. Do not retry.]",
        )

    def test_sanitize_tool_image_dict_default_path(self):
        messages = [{"role": "tool", "content": {"type": "image"}}]
        result = self.mixin._sanitize_vision_error_messages(messages)
        self.assertEqual(
            result[0]["content"],
            "ERR: cannot read image 'image' [Hint: You do not support vision. Tell user you cannot view images. Do not retry.]",
        )

    def test_sanitize_tool_image_str_with_path(self):
        messages = [{"role": "tool", "content": '{"type": "image", "path": "/tmp/img.png"}'}]
        result = self.mixin._sanitize_vision_error_messages(messages)
        self.assertEqual(
            result[0]["content"],
            "ERR: cannot read image '/tmp/img.png' [Hint: You do not support vision. Tell user you cannot view images. Do not retry.]",
        )

    def test_sanitize_tool_image_str_without_path(self):
        messages = [{"role": "tool", "content": "[Image file: /tmp/b.png]"}]
        result = self.mixin._sanitize_vision_error_messages(messages)
        self.assertEqual(
            result[0]["content"],
            "ERR: cannot read image 'image' [Hint: You do not support vision. Tell user you cannot view images. Do not retry.]",
        )

    def test_sanitize_tool_plain_content_kept(self):
        messages = [{"role": "tool", "content": "plain tool output"}]
        self.assertEqual(self.mixin._sanitize_vision_error_messages(messages), messages)

    def test_sanitize_other_roles_kept(self):
        messages = [
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "plain text"},
        ]
        self.assertEqual(self.mixin._sanitize_vision_error_messages(messages), messages)


if __name__ == "__main__":
    unittest.main()
