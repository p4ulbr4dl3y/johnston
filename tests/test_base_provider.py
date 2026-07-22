import os
import shutil
import tempfile
import unittest

from core.base_provider import BaseAgent
from tools.registry import execute_tool


class TestBaseProviderTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    async def test_create_and_read_tool(self):
        file_path = os.path.join(self.test_dir, "test.txt")

        # Test Create
        res_create = await execute_tool("Create", {"path": file_path, "content": "hello world"})
        self.assertIn("Success", res_create)
        self.assertTrue(os.path.exists(file_path))

        # Test Read
        res_read = await execute_tool("Read", {"path": file_path})
        self.assertIn("hello world", res_read)

    async def test_read_missing_file(self):
        file_path = os.path.join(self.test_dir, "missing.txt")
        res_read = await execute_tool("Read", {"path": file_path})
        self.assertIn("Error", res_read)

    async def test_edit_tool(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("Create", {"path": file_path, "content": "line1\nline2\nline3"})

        # Test valid Edit
        res_edit = await execute_tool("Edit", {
            "path": file_path,
            "old_string": "line2",
            "new_string": "line_two"
        })
        self.assertIn("line2", res_edit)  # check diff contains old text
        self.assertIn("line_two", res_edit)  # check diff contains new text

        # Verify content
        with open(file_path, "r") as f:
            content = f.read()
        self.assertEqual(content, "line1\nline_two\nline3")

    async def test_read_line_range_pagination(self):
        file_path = os.path.join(self.test_dir, "range_test.txt")
        await execute_tool("Create", {"path": file_path, "content": "line1\nline2\nline3\nline4"})

        res_read = await execute_tool("Read", {"path": file_path, "start_line": 2, "end_line": 3})
        self.assertIn("Lines 2-3", res_read)
        self.assertIn("2 | line2", res_read)
        self.assertIn("3 | line3", res_read)
        self.assertNotIn("line1", res_read)

    async def test_edit_missing_text(self):
        file_path = os.path.join(self.test_dir, "edit_test.txt")
        await execute_tool("Create", {"path": file_path, "content": "line1\nline2\nline3"})

        res_edit = await execute_tool("Edit", {
            "path": file_path,
            "old_string": "missing_line",
            "new_string": "replacement"
        })
        self.assertIn("Error", res_edit)

    async def test_edit_ambiguous_occurrences(self):
        file_path = os.path.join(self.test_dir, "ambiguous_test.txt")
        await execute_tool("Create", {"path": file_path, "content": "duplicate\nmiddle\nduplicate"})

        res_edit = await execute_tool("Edit", {
            "path": file_path,
            "old_string": "duplicate",
            "new_string": "replacement"
        })
        self.assertIn("matches 2 occurrences", res_edit)

    async def test_list_dir_tool(self):
        os.makedirs(os.path.join(self.test_dir, "folder_a"))
        await execute_tool("Create", {"path": os.path.join(self.test_dir, "file_b.txt"), "content": "data"})

        res_listdir = await execute_tool("ListDir", {"path": self.test_dir})
        self.assertIn("[DIR]  folder_a/", res_listdir)
        self.assertIn("[FILE] file_b.txt", res_listdir)

    async def test_glob_tool(self):
        os.makedirs(os.path.join(self.test_dir, "subdir"))
        await execute_tool("Create", {"path": os.path.join(self.test_dir, "file1.txt"), "content": "a"})
        await execute_tool("Create", {"path": os.path.join(self.test_dir, "subdir", "file2.log"), "content": "b"})

        # Glob txt
        res_glob = await execute_tool("Glob", {"pattern": "*.txt"})
        self.assertIn("file1.txt", res_glob)
        self.assertNotIn("file2.log", res_glob)

    async def test_grep_tool(self):
        file1 = os.path.join(self.test_dir, "file1.txt")
        file2 = os.path.join(self.test_dir, "file2.txt")
        await execute_tool("Create", {"path": file1, "content": "banana apple pear"})
        await execute_tool("Create", {"path": file2, "content": "grape orange cherry"})

        # Grep apple
        res_grep = await execute_tool("Grep", {"pattern": "apple"})
        self.assertIn("file1.txt", res_grep)
        self.assertIn("banana apple pear", res_grep)
        self.assertNotIn("file2.txt", res_grep)

    async def test_bash_tool_sync(self):
        # Sync bash execution
        res_bash = await execute_tool("Bash", {"command": "echo 'hello bash'"})
        self.assertEqual(res_bash.strip(), "hello bash")

    def test_init_and_compact_commands_registered(self):
        from commands import COMMAND_REGISTRY
        self.assertIn("/init", COMMAND_REGISTRY)
        self.assertIn("/compact", COMMAND_REGISTRY)
        self.assertIn("/plan", COMMAND_REGISTRY)
        self.assertIn("/build", COMMAND_REGISTRY)
        self.assertIn("/mode", COMMAND_REGISTRY)

    async def test_plan_exit_tool(self):
        class DummyAgent:
            mode = "plan"

        class DummyApp:
            agent = DummyAgent()
            footer_refreshed = False
            notified = None

            def refresh_status_footer(self):
                self.footer_refreshed = True

            def notify(self, msg):
                self.notified = msg

        app = DummyApp()
        res = await execute_tool("PlanExit", {}, app=app)
        self.assertEqual(app.agent.mode, "build")
        self.assertTrue(app.footer_refreshed)
        self.assertIn("Switched to build mode", res)

    async def test_plan_exit_dynamic_mode_switch(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        agent.mode = "plan"
        res = await execute_tool("PlanExit", {}, app=agent)
        self.assertEqual(agent.mode, "build")
        self.assertIn("Switched to build mode", res)

    async def test_compact_history_short(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        agent.history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"}
        ]
        success, msg = await agent.compact_history()
        self.assertFalse(success)
        self.assertIn("too short", msg)

    async def test_auto_compaction_trigger(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        agent.history = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
            {"role": "user", "content": "e" * 200},
        ]
        compacted = False
        async def mock_compact():
            nonlocal compacted
            compacted = True
            return True, "compacted"

        with unittest.mock.patch("core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock) as mock_limit:
            mock_limit.return_value = 100
            with unittest.mock.patch.object(agent, "compact_history", new_callable=unittest.mock.AsyncMock) as mock_comp:
                mock_comp.return_value = (True, "compacted")
                try:
                    async for _ in agent.stream_steps("trigger"):
                        pass
                except Exception:
                    pass
                mock_comp.assert_called_once()

    async def test_manage_task_tool(self):
        class DummyApp:
            background_tasks = []

        app = DummyApp()
        res_list = await execute_tool("ManageTask", {"action": "list"}, app=app)
        self.assertIn("No background tasks currently active", res_list)

    async def test_task_tool_foreground(self):
        class DummySubAgent:
            system_prompt = "system"
            tools = []
            async def stream_steps(self, prompt):
                yield ("bot_text", "Subagent answer for: " + prompt, "")

        class DummyPM:
            def create_active_agent(self):
                return DummySubAgent()

        class DummyApp:
            pm = DummyPM()

        app = DummyApp()
        res = await execute_tool("Subagent", {"prompt": "do research", "description": "research task"}, app=app)
        self.assertIn("<task_result>", res)
        self.assertIn("Subagent answer for: do research", res)

    async def test_task_tool_background(self):
        class DummySubAgent:
            system_prompt = "system"
            tools = []
            async def stream_steps(self, prompt):
                yield ("bot_text", "BG Subagent answer", "")

        class DummyPM:
            def create_active_agent(self):
                return DummySubAgent()

        class DummyApp:
            pm = DummyPM()
            background_tasks = []
            notified = []

            def notify(self, msg):
                self.notified.append(msg)

            def refresh_status_footer(self):
                pass

            def generate_ai_response(self, text, show_in_ui=False):
                pass

        app = DummyApp()
        res = await execute_tool("Subagent", {"prompt": "bg task", "description": "bg job", "background": True}, app=app)
        self.assertIn("launched in background", res)
        self.assertEqual(len(app.background_tasks), 1)
        self.assertTrue(app.background_tasks[0].task_id.startswith("subagent-"))

    def test_truncate_output_helper(self):
        from tools.base import truncate_output
        short_text = "hello"
        self.assertEqual(truncate_output(short_text, max_chars=10), "hello")

        long_text = "a" * 100
        truncated = truncate_output(long_text, max_chars=10, hint="Use line ranges.")
        self.assertTrue(truncated.startswith("aaaaaaaaaa"))
        self.assertIn("Output truncated at 10 chars. Use line ranges.", truncated)

    def test_agent_cost_usd_calculation(self):
        agent = BaseAgent(api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov")
        self.assertEqual(agent.cost_usd, 0.0)
        metrics = agent.get_metrics()
        self.assertEqual(metrics["cost_usd"], 0.0)

        agent.cost_usd = 0.0025
        self.assertEqual(agent.get_metrics()["cost_usd"], 0.0025)

        agent.clear_history()
        self.assertEqual(agent.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
