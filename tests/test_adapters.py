import unittest

from core.adapters import AnthropicAdapter, GeminiAdapter, OllamaAdapter, OpenAIAdapter, get_adapter


class TestAdapters(unittest.TestCase):
    def test_get_adapter(self):
        self.assertIsInstance(get_adapter("openai"), OpenAIAdapter)
        self.assertIsInstance(get_adapter("anthropic"), AnthropicAdapter)
        self.assertIsInstance(get_adapter("gemini"), GeminiAdapter)
        self.assertIsInstance(get_adapter("ollama"), OllamaAdapter)
        self.assertIsInstance(get_adapter("unknown"), OpenAIAdapter)


if __name__ == "__main__":
    unittest.main()
