import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.background_task import BackgroundSubagent, BackgroundTask
from core.models_catalog import ModelsCatalog, format_context_tokens, get_context_window


class TestBackgroundTask(unittest.IsolatedAsyncioTestCase):
    async def test_background_task_completion_callback(self):
        cb_called = False
        captured_res = ""

        def on_completed(task_id, cmd, res):
            nonlocal cb_called, captured_res
            cb_called = True
            captured_res = res

        # Create dummy subprocess mock with stdout
        mock_proc = MagicMock()
        mock_proc.wait = MagicMock(return_value=asyncio.sleep(0.01))

        # Create stdout stream
        reader = asyncio.StreamReader()
        reader.feed_data(b"Line 1\nLine 2\n")
        reader.feed_eof()
        mock_proc.stdout = reader

        bg_task = BackgroundTask("task_1", "echo test", mock_proc)
        bg_task.is_background = True
        read_task = bg_task.start_reading(app=None, on_completed_cb=on_completed)
        await read_task

        self.assertFalse(bg_task.is_running)
        self.assertTrue(cb_called)
        self.assertIn("Line 1\nLine 2\n", captured_res)

    async def test_background_task_kill(self):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock(return_value=asyncio.sleep(0.01))

        bg_task = BackgroundTask("task_2", "sleep 100", mock_proc)
        await bg_task.kill()

        self.assertFalse(bg_task.is_running)
        mock_proc.terminate.assert_called_once()
        self.assertIn("Task terminated by user", "".join(bg_task.output))

    async def test_background_task_send_input(self):
        mock_proc = MagicMock()
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = MagicMock(return_value=asyncio.sleep(0))
        mock_proc.stdin = mock_stdin

        bg_task = BackgroundTask("task_3", "interactive_cmd", mock_proc)
        res = await bg_task.send_input("hello stdin")
        self.assertIn("Input sent to task task_3", res)
        mock_stdin.write.assert_called_once_with(b"hello stdin\n")

    def test_process_carriage_returns(self):
        from core.background_task import process_carriage_returns
        raw = "Downloading 0%\rDownloading 50%\rDownloading 100%\nDone\n"
        cleaned = process_carriage_returns(raw)
        self.assertEqual(cleaned, "Downloading 100%\nDone\n")

    def test_get_formatted_output_chunks(self):
        bg_task = BackgroundTask("task_git", "git clone", None)
        bg_task.output = [
            "Receiving objects: 26% (127/485)\r",
            "Receiving objects: 27% (131/485)\r",
            "Receiving objects: 100% (485/485)\n",
            "Resolving deltas: 100% (17/17)\n"
        ]
        res = bg_task.get_formatted_output()
        self.assertEqual(res, "Receiving objects: 100% (485/485)\nResolving deltas: 100% (17/17)\n")

    async def test_background_subagent_kill(self):
        async def dummy_subagent():
            await asyncio.sleep(100)

        task = asyncio.create_task(dummy_subagent())
        subagent = BackgroundSubagent("sub_1", "explore codebase", task)
        self.assertTrue(subagent.is_running)

        await subagent.kill()
        await asyncio.sleep(0.01)
        self.assertFalse(subagent.is_running)
        self.assertTrue(task.cancelled() or task.cancelling())


class TestModelsCatalog(unittest.TestCase):
    def test_format_context_tokens(self):
        self.assertEqual(format_context_tokens(1_000_000), "1M")
        self.assertEqual(format_context_tokens(2_000_000), "2M")
        self.assertEqual(format_context_tokens(128_000), "128k")
        self.assertEqual(format_context_tokens(64_000), "64k")
        self.assertEqual(format_context_tokens(500), "500")

    def test_init_does_not_start_background_refresh(self):
        with patch.object(ModelsCatalog, "_trigger_background_refresh") as mock_refresh:
            ModelsCatalog()

        mock_refresh.assert_not_called()

    def test_get_context_limit_default_and_cache(self):
        catalog = ModelsCatalog()
        # Default fallback
        limit = catalog.get_context_limit("unknown_provider", "non_existent_model")
        self.assertEqual(limit, 128000)

    def test_get_model_display_name(self):
        catalog = ModelsCatalog()
        self.assertEqual(catalog.get_model_display_name("opencode", ""), "")
        name = catalog.get_model_display_name("opencode", "deepseek-v4-flash")
        self.assertIn("deepseek", name.lower())

    def test_get_context_window_helper(self):
        window = get_context_window("opencode", "deepseek-v4-flash")
        self.assertIsInstance(window, str)

    def test_get_model_pricing(self):
        catalog = ModelsCatalog()
        catalog._pricing = {
            "openai/gpt-4o": {"prompt": 0.0000025, "completion": 0.00001}
        }
        pricing = catalog.get_model_pricing("openrouter", "openai/gpt-4o")
        self.assertEqual(pricing["prompt"], 0.0000025)
        self.assertEqual(pricing["completion"], 0.00001)

        pricing_unknown = catalog.get_model_pricing("openrouter", "unknown")
        self.assertEqual(pricing_unknown["prompt"], 0.0)
        self.assertEqual(pricing_unknown["completion"], 0.0)

    def test_fuzzy_matching_local_models(self):
        cat = ModelsCatalog()
        cat._limits = {"google/gemma-4-31b": 262144, "gemma-4": 262144}
        cat._reasoning = ["google/gemma-4-31b", "gemma-4"]

        # Test exact match
        self.assertEqual(cat.get_context_limit("google", "gemma-4"), 262144)
        # Test fuzzy match with MLX/4bit suffix
        self.assertEqual(cat.get_context_limit("omlx", "gemma-4-E4B-it-MLX-4bit"), 262144)
        self.assertTrue(cat.supports_reasoning("omlx", "gemma-4-E4B-it-MLX-4bit"))


    def test_output_limit_and_reasoning_and_open_weights(self):
        cat = ModelsCatalog()
        cat._limits = {"deepseek/deepseek-v4-pro": 1000000}
        cat._output_limits = {"deepseek/deepseek-v4-pro": 384000}
        cat._reasoning = ["deepseek/deepseek-v4-pro"]
        cat._open_weights = ["deepseek/deepseek-v4-pro"]
        cat._descriptions = {"deepseek/deepseek-v4-pro": "Open MoE flagship"}

        self.assertEqual(cat.get_output_limit("deepseek", "deepseek-v4-pro"), 384000)
        self.assertTrue(cat.supports_reasoning("deepseek", "deepseek-v4-pro"))
        self.assertTrue(cat.is_open_weights("deepseek", "deepseek-v4-pro"))
        self.assertEqual(cat.get_model_description("deepseek", "deepseek-v4-pro"), "Open MoE flagship")

    def test_save_and_load_cache(self):
        cat = ModelsCatalog()
        cat._limits = {"test/m1": 100000}
        cat._names = {"test/m1": "Test Model 1"}
        cat._pricing = {"test/m1": {"prompt": 0.001, "completion": 0.002}}

        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("core.models_catalog.CACHE_FILE", tmp_path):
                cat.save_cache()
                cat2 = ModelsCatalog()
                self.assertTrue(cat2.load_cache())
                self.assertEqual(cat2.get_context_limit("test", "m1"), 100000)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class TestModelsCatalogAsync(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_catalog_mocked(self):
        cat = ModelsCatalog()

        mdev_json = {
            "openai": {
                "models": {
                    "gpt-4o": {
                        "name": "GPT-4o",
                        "description": "Flagship model",
                        "limit": {"context": 128000, "output": 4096},
                        "modalities": {"input": ["text"]},
                        "reasoning": True,
                        "open_weights": False,
                        "cost": {"input": 2.5, "output": 10.0}
                    }
                }
            }
        }
        openrouter_json = {
            "data": [
                {
                    "id": "anthropic/claude-3.5-sonnet",
                    "name": "Anthropic: Claude 3.5 Sonnet",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"}
                }
            ]
        }

        import httpx

        mock_mdev_res = httpx.Response(200, json=mdev_json)
        mock_or_res = httpx.Response(200, json=openrouter_json)

        def get_mock_res(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "models.dev" in url:
                return mock_mdev_res
            return mock_or_res

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_async_get:
            mock_async_get.side_effect = get_mock_res

            limits = await cat.refresh()
            self.assertIn("openai/gpt-4o", limits)
            self.assertEqual(limits["openai/gpt-4o"], 128000)
            self.assertTrue(cat.supports_reasoning("openai", "gpt-4o"))

            self.assertIn("anthropic/claude-3.5-sonnet", limits)
            self.assertEqual(limits["anthropic/claude-3.5-sonnet"], 200000)




if __name__ == "__main__":
    unittest.main()

