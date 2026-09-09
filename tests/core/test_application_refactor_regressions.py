"""Regression tests for application layer refactoring and bugfixes."""
import concurrent.futures
import tempfile
from unittest.mock import MagicMock, patch

from johnston.core.application.generation.prompt_builder import PromptBuilder
from johnston.core.application.rules.rules import RuleDefinition, RulesManager
from johnston.core.application.session.rewind import rewind_session


class TestRewindEventLoopSafety:
    def test_rewind_without_event_loop_does_not_raise(self):
        agent = MagicMock()
        agent.history = [{"role": "user", "content": "hello"}]
        agent.rewind_git_restore_task = None
        user_msgs = [(0, "hello")]

        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no running event loop")):
            rewind_session(
                agent=agent,
                user_msgs=user_msgs,
                selected_child_idx=0,
                curr_sid="sess-1",
                project_path="/proj",
                restore_git=True,
                rollback_ui=MagicMock(),
                load_text_into_input=MagicMock(),
                save_session_cb=MagicMock(),
                refresh_footer_cb=MagicMock(),
            )

        assert agent.rewind_git_restore_task is None

    def test_rewind_with_closed_loop_does_not_raise(self):
        agent = MagicMock()
        agent.history = [{"role": "user", "content": "test prompt"}]
        agent.rewind_git_restore_task = None
        user_msgs = [(0, "test prompt")]

        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = True

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            rewind_session(
                agent=agent,
                user_msgs=user_msgs,
                selected_child_idx=0,
                curr_sid="sess-1",
                project_path="/proj",
                restore_git=True,
                rollback_ui=MagicMock(),
                load_text_into_input=MagicMock(),
                save_session_cb=MagicMock(),
                refresh_footer_cb=MagicMock(),
            )

        mock_loop.create_task.assert_not_called()
        assert agent.rewind_git_restore_task is None


class TestPromptBuilderDeterministicToolIdent:
    def test_identical_dicts_produce_same_ident(self):
        tool1 = {
            "type": "function",
            "function": {
                "name": "shell_exec",
                "description": "Execute a command",
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            },
        }
        tool2 = {
            "type": "function",
            "function": {
                "name": "shell_exec",
                "description": "Execute a command",
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            },
        }
        assert id(tool1) != id(tool2)

        pb1 = PromptBuilder("Test prompt", [tool1])
        pb2 = PromptBuilder("Test prompt", [tool2])

        tools_res1 = pb1.build_tools()
        tools_res2 = pb2.build_tools()

        assert tools_res1 == tools_res2

    def test_tool_content_change_produces_different_ident(self):
        tool1 = {
            "type": "function",
            "function": {"name": "test_fn", "description": "desc 1"},
        }
        tool2 = {
            "type": "function",
            "function": {"name": "test_fn", "description": "desc 2"},
        }
        pb1 = PromptBuilder("Test prompt", [tool1])
        pb2 = PromptBuilder("Test prompt", [tool2])
        res1 = pb1.build_tools()
        res2 = pb2.build_tools()
        assert res1[0]["function"]["description"] == "desc 1"
        assert res2[0]["function"]["description"] == "desc 2"


class TestRulesManagerThreadSafety:
    def test_rules_manager_has_lock(self):
        rm = RulesManager()
        assert hasattr(rm, "_lock")

    def test_concurrent_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rm = RulesManager()

            def worker(i):
                rm.load_rules(project_dir=tmpdir, include_global=False)
                if i % 3 == 0:
                    rm.invalidate_cache()
                _ = rm.rules
                _ = rm.get_active_rules(project_dir=tmpdir, include_global=False)
                return True

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(worker, i) for i in range(40)]
                results = [f.result() for f in futures]

            assert all(results)


class TestApplicationInitPackages:
    def test_rules_package_init_exports(self):
        import johnston.core.application.rules as rules_pkg

        assert hasattr(rules_pkg, "RulesManager")
        assert hasattr(rules_pkg, "RuleDefinition")
        assert rules_pkg.RulesManager is RulesManager
        assert rules_pkg.RuleDefinition is RuleDefinition

    def test_skills_package_init_exports(self):
        import johnston.core.application.skills as skills_pkg

        assert hasattr(skills_pkg, "extract_and_inject_skills")
        assert hasattr(skills_pkg, "SkillManager")
        assert hasattr(skills_pkg, "get_skill_manager")


class TestPermissionCycleRemoval:
    def test_no_circular_import_between_config_and_manager(self):
        # Verify permission_config does not import permission_manager at module level
        import johnston.core.application.permission.helpers as helpers
        import johnston.core.application.permission.permission_config as pconfig
        import johnston.core.application.permission.permission_manager as pmanager

        assert hasattr(helpers, "is_git_repository")
        assert hasattr(helpers, "CONFIG_FILE")
        assert hasattr(pconfig, "PermissionConfigStore")
        assert hasattr(pmanager, "PermissionManager")
        assert not hasattr(pconfig, "PermissionManager")
