import asyncio
import unittest
from unittest.mock import MagicMock

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

    def test_get_context_limit_default_and_cache(self):
        catalog = ModelsCatalog()
        # Default fallback
        limit = catalog.get_context_limit("unknown_provider", "non_existent_model")
        self.assertEqual(limit, 128000)

    def test_get_model_display_name(self):
        catalog = ModelsCatalog()
        self.assertEqual(catalog.get_model_display_name("opencode", ""), "")
        name = catalog.get_model_display_name("opencode", "deepseek-v4-flash")
        self.assertIn("DeepSeek", name)

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


if __name__ == "__main__":
    unittest.main()
