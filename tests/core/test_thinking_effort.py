import json
import os
import tempfile
import unittest
import unittest.mock

from core.thinking_effort import (
    build_gemini_thinking_config,
    build_openai_thinking_kwargs,
    normalize_thinking_effort,
)


class TestThinkingEffortResolver(unittest.TestCase):
    def test_normalize_thinking_effort(self):
        self.assertEqual(normalize_thinking_effort("HIGH"), "high")
        self.assertIsNone(normalize_thinking_effort("auto"))
        self.assertIsNone(normalize_thinking_effort("invalid"))

    def test_openai_kwargs(self):
        self.assertEqual(build_openai_thinking_kwargs("high"), {"reasoning_effort": "high"})
        self.assertEqual(build_openai_thinking_kwargs("auto"), {})

    def test_gemini_model_specific_shapes(self):
        self.assertEqual(build_gemini_thinking_config("gemini-3.6-flash", "low"), {"thinkingLevel": "low"})
        self.assertEqual(
            build_gemini_thinking_config("gemini-2.5-flash", "medium"),
            {"thinkingBudget": 8192, "includeThoughts": True},
        )
        self.assertIsNone(build_gemini_thinking_config("gemini-1.5-pro", "high"))

    def test_thinking_effort_screen_marks_active_but_highlights_auto(self):
        from widgets.screens.thinking_effort import ThinkingEffortScreen

        screen = ThinkingEffortScreen("medium")

        self.assertEqual(screen.default_value, "auto")
        self.assertIn(r"\[ACTIVE]", screen.raw_options[2])
        self.assertNotIn(r"\[ACTIVE]", screen.raw_options[0])


class TestThinkingEffortProviderManager(unittest.TestCase):
    def test_provider_model_effort_override_and_default(self):
        import core.provider_manager as pm_mod

        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            providers_path = os.path.join(tmp, "providers.json")
            with open(providers_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "custom": {
                            "key": "custom",
                            "name": "Custom",
                            "base_url": "http://example.test",
                            "model": "m1",
                            "api_type": "openai",
                            "reasoning_effort": "low",
                        }
                    },
                    f,
                )

            with unittest.mock.patch.object(pm_mod, "CONFIG_FILE", config_path), unittest.mock.patch.object(
                pm_mod, "PROVIDERS_JSON_FILE", providers_path
            ), unittest.mock.patch.object(pm_mod, "CONFIG_DIR", tmp):
                pm = pm_mod.ProviderManager()
                self.assertEqual(pm.get_provider_thinking_effort("custom", "m1"), "auto")

                pm.set_provider_thinking_effort("custom", "m1", "high")
                self.assertEqual(pm.get_provider_thinking_effort("custom", "m1"), "high")

                pm.set_provider_thinking_effort("custom", "m1", "auto")
                self.assertEqual(pm.get_provider_thinking_effort("custom", "m1"), "auto")


class TestThinkingEffortOpenAIRequest(unittest.IsolatedAsyncioTestCase):
    async def test_base_agent_sends_openai_reasoning_effort(self):
        from core.base_provider import BaseAgent

        agent = BaseAgent(
            api_key="test",
            model="gpt-test",
            base_url="http://example.test",
            tools=[],
            thinking_effort="high",
        )
        self.addAsyncCleanup(agent.close)

        mock_delta = unittest.mock.MagicMock()
        mock_delta.content = "done"
        mock_delta.reasoning_content = None
        mock_delta.reasoning = None
        mock_delta.tool_calls = None
        mock_choice = unittest.mock.MagicMock()
        mock_choice.delta = mock_delta
        chunk = unittest.mock.MagicMock()
        chunk.choices = [mock_choice]
        chunk.usage = None

        async def mock_aiter():
            yield chunk

        mock_response = unittest.mock.MagicMock()
        mock_response.__aiter__.side_effect = mock_aiter

        with unittest.mock.patch.object(agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock) as create:
            create.return_value = mock_response
            events = []
            async for event in agent.stream_steps("hello"):
                events.append(event)

        self.assertEqual(create.call_args.kwargs["reasoning_effort"], "high")
        self.assertTrue(any(event[0] == "bot_delta" for event in events))


class _FakeStream:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class _FakeHttpClient:
    captured_payload = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        _FakeHttpClient.captured_payload = kwargs.get("json")
        return _FakeStream(self.lines)


class TestThinkingEffortAdapters(unittest.IsolatedAsyncioTestCase):
    async def test_anthropic_payload_effort(self):
        from core.adapters import AnthropicAdapter

        class Client(_FakeHttpClient):
            lines = [
                'data: {"type":"message_start","message":{"usage":{"input_tokens":1}}}',
                'data: {"type":"message_stop"}',
            ]

        with unittest.mock.patch("core.adapters.httpx.AsyncClient", Client):
            async for _ in AnthropicAdapter().stream_chat("", "key", "claude-test", [{"role": "user", "content": "hi"}], thinking_effort="medium"):
                pass
        self.assertEqual(_FakeHttpClient.captured_payload["output_config"], {"effort": "medium"})

    async def test_gemini_payload_effort(self):
        from core.adapters import GeminiAdapter

        class Client(_FakeHttpClient):
            lines = ['data: {"usageMetadata":{"promptTokenCount":1,"candidatesTokenCount":1,"totalTokenCount":2}}']

        with unittest.mock.patch("core.adapters.httpx.AsyncClient", Client):
            async for _ in GeminiAdapter().stream_chat("", "key", "gemini-2.5-flash", [{"role": "user", "content": "hi"}], thinking_effort="high"):
                pass
        self.assertEqual(
            _FakeHttpClient.captured_payload["generationConfig"]["thinkingConfig"],
            {"thinkingBudget": 24576, "includeThoughts": True},
        )

    async def test_ollama_payload_effort(self):
        from core.adapters import OllamaAdapter

        class Client(_FakeHttpClient):
            lines = ['{"done": true, "prompt_eval_count": 1, "eval_count": 1}']

        with unittest.mock.patch("core.adapters.httpx.AsyncClient", Client):
            async for _ in OllamaAdapter().stream_chat("", "", "qwen3", [{"role": "user", "content": "hi"}], thinking_effort="low"):
                pass
        self.assertEqual(_FakeHttpClient.captured_payload["think"], "low")


class TestThinkingEffortCommand(unittest.IsolatedAsyncioTestCase):
    async def test_command_saves_effort_and_preserves_mode(self):
        from core.commands import ThinkingEffortCommand

        class Agent:
            def __init__(self):
                self.model = "m1"
                self.mode = "explore"
                self.history = [{"role": "user", "content": "hi"}]

        class PM:
            def __init__(self):
                self.saved = None

            def get_active_provider_key(self):
                return "p1"

            def get_provider_model(self, provider_key):
                return "m1"

            def get_provider_thinking_effort(self, provider_key, model_name):
                return ""

            def set_provider_thinking_effort(self, provider_key, model_name, effort):
                self.saved = (provider_key, model_name, effort)

            def create_active_agent(self):
                return Agent()

        class Input:
            focused = False

            def focus(self):
                self.focused = True

        class App:
            def __init__(self):
                self.agent = Agent()
                self.mode = "explore"
                self.pm = PM()
                self.input = Input()
                self.refreshed = False
                self.messages = []

            def push_screen(self, screen, callback=None):
                self.screen = screen
                callback("high")

            def query_one(self, *args, **kwargs):
                return self.input

            def refresh_status_footer(self):
                self.refreshed = True

            def notify(self, message, severity="info"):
                self.messages.append((message, severity))

        app = App()
        await ThinkingEffortCommand().execute(app)

        self.assertEqual(app.pm.saved, ("p1", "m1", "high"))
        self.assertEqual(app.agent.mode, "explore")
        self.assertEqual(app.mode, "explore")
        self.assertEqual(app.agent.history, [{"role": "user", "content": "hi"}])
        self.assertTrue(app.refreshed)
        self.assertTrue(app.input.focused)
