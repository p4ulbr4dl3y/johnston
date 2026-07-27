import unittest

from core.base_provider import format_api_error


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


if __name__ == "__main__":
    unittest.main()
