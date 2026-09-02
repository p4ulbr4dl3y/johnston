"""Comprehensive coverage tests for widgets/app modules.

Covers:
- widgets/app/session_state.py
- widgets/app/role_service.py
- widgets/app/dispatch.py
- widgets/app/command_provider.py
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from widgets.app.command_provider import (
    _build_command_suggestions,
    get_all_command_suggestions,
)
from widgets.app.dispatch import (
    _load_skill_blocks,
    _resolve_skills,
    build_command_registry,
    handle_slash_command,
)
from widgets.app.role_service import reconcile_active_agent, toggle_agent_role
from widgets.app.session_state import collect_session_data, recompute_context_tokens

# ============================================================================
# session_state.py tests
# ============================================================================


class TestSessionStateCoverage:
    def test_collect_session_data_no_session(self):
        app = SimpleNamespace(
            sm=MagicMock(get=MagicMock(return_value=None)),
            current_session_id="sess-123",
        )
        assert collect_session_data(app) is None

    def test_collect_session_data_no_user_messages(self):
        # Empty messages
        session = SimpleNamespace(messages=[], _title="Test")
        app = SimpleNamespace(
            sm=MagicMock(get=MagicMock(return_value=session)),
            current_session_id="sess-123",
        )
        assert collect_session_data(app) is None

        # Only assistant or non-dict messages
        session.messages = ["not-a-dict", {"type": "assistant", "content": "hello"}]
        assert collect_session_data(app) is None

        # Hidden user message (e.g. is_ui_visible_user_message returns False)
        session.messages = [{"type": "user", "content": "hidden", "role": "system"}]
        with patch("widgets.app.session_state.is_ui_visible_user_message", return_value=False):
            assert collect_session_data(app) is None

    def test_collect_session_data_success_with_agent(self):
        session = SimpleNamespace(
            messages=[{"type": "user", "content": "hello"}],
            _title="My Chat",
        )
        agent = SimpleNamespace(
            role="architect",
            history=[{"role": "user", "content": "hello"}],
            tokens_input=100,
            tokens_output=50,
            total_tokens=150,
            cost_usd=0.005,
            last_context_tokens=120,
            tokens_cache_read=20,
        )
        app = SimpleNamespace(
            sm=MagicMock(get=MagicMock(return_value=session)),
            current_session_id="sess-123",
            agent=agent,
            role="worker",
        )
        with patch("widgets.app.session_state.is_ui_visible_user_message", return_value=True):
            data = collect_session_data(app)

        assert data is not None
        assert data["id"] == "sess-123"
        assert data["title"] == "My Chat"
        assert data["role"] == "architect"
        assert data["messages"] == [{"type": "user", "content": "hello"}]
        assert data["agent_history"] == [{"role": "user", "content": "hello"}]
        assert data["tokens_input"] == 100
        assert data["tokens_output"] == 50
        assert data["total_tokens"] == 150
        assert data["cost_usd"] == 0.005
        assert data["last_context_tokens"] == 120
        assert data["tokens_cache_read"] == 20

    def test_collect_session_data_success_defaults(self):
        session = SimpleNamespace(
            messages=[{"type": "user", "content": "hello"}],
        )  # no _title
        app = SimpleNamespace(
            sm=MagicMock(get=MagicMock(return_value=session)),
            current_session_id="sess-456",
            agent=None,
            role="coder",
        )
        with patch("widgets.app.session_state.is_ui_visible_user_message", return_value=True):
            data = collect_session_data(app)

        assert data is not None
        assert data["id"] == "sess-456"
        assert data["title"] == ""
        assert data["role"] == "coder"
        assert data["agent_history"] == []
        assert data["tokens_input"] == 0
        assert data["tokens_output"] == 0
        assert data["total_tokens"] == 0
        assert data["cost_usd"] == 0.0
        assert data["last_context_tokens"] == 0
        assert data["tokens_cache_read"] == 0

    def test_recompute_context_tokens_already_set(self):
        agent = SimpleNamespace(history=[1, 2, 3])
        assert recompute_context_tokens(agent, 450) == 450

    def test_recompute_context_tokens_no_history(self):
        agent = SimpleNamespace(history=[])
        assert recompute_context_tokens(agent, 0) == 0

        agent_no_attr = SimpleNamespace()
        assert recompute_context_tokens(agent_no_attr, 0) == 0

    def test_recompute_context_tokens_calculation(self):
        agent = SimpleNamespace(
            system_prompt="You are helpful",
            tools=[{"name": "read_file"}],
            history=[{"role": "user", "content": "test"}],
            role="worker",
            is_subagent=True,
            subagent_schema={"name": "test"},
        )
        with patch("core.application.generation.prompt_builder.PromptBuilder") as mock_builder_cls, patch(
            "core.infrastructure.runtime.token_util.estimate_tokens", side_effect=lambda x: len(str(x))
        ):
            mock_builder = MagicMock()
            mock_builder.build_system_prompt.return_value = "prompt"
            mock_builder.build_tools.return_value = ["tool"]
            mock_builder_cls.return_value = mock_builder

            tokens = recompute_context_tokens(agent, 0)
            mock_builder_cls.assert_called_once_with(
                "You are helpful",
                [{"name": "read_file"}],
                role="worker",
                is_subagent=True,
                subagent_schema={"name": "test"},
            )
            assert tokens > 0


# ============================================================================
# role_service.py tests
# ============================================================================


class TestRoleServiceCoverage:
    def test_toggle_agent_role_standard(self):
        mock_registry = MagicMock()
        mock_registry.list_roles.return_value = {"worker": {}, "architect": {}, "ask": {}}

        app = SimpleNamespace(
            agent=SimpleNamespace(role="worker"),
            role="worker",
            sm=SimpleNamespace(get=MagicMock(return_value=SimpleNamespace(role="worker"))),
            current_session_id="sess-1",
            save_current_session=MagicMock(),
            refresh_status_footer=MagicMock(),
        )

        with patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_registry):
            res = toggle_agent_role(app)

        assert res is True
        assert app.agent.role == "architect"
        assert app.role == "architect"
        session = app.sm.get.return_value
        assert session.role == "architect"
        app.save_current_session.assert_called_once()
        app.refresh_status_footer.assert_called_once()

    def test_toggle_agent_role_wrap_around_and_unknown_current(self):
        mock_registry = MagicMock()
        mock_registry.list_roles.return_value = {"worker": {}, "architect": {}}

        # Unknown current role -> picks index 0 ("worker")
        app = SimpleNamespace(
            agent=SimpleNamespace(role="unknown_role"),
            role="unknown_role",
            refresh_status_footer=MagicMock(),
        )
        with patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_registry):
            toggle_agent_role(app)
        assert app.role == "worker"

        # Wrap around: architect -> worker
        app.agent.role = "architect"
        with patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_registry):
            toggle_agent_role(app)
        assert app.role == "worker"

    def test_toggle_agent_role_no_sm_or_no_session(self):
        mock_registry = MagicMock()
        mock_registry.list_roles.return_value = {"worker": {}, "architect": {}}

        # App without sm
        app = SimpleNamespace(
            agent=SimpleNamespace(role="worker"),
            role="worker",
            refresh_status_footer=MagicMock(),
        )
        with patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_registry):
            toggle_agent_role(app)
        assert app.role == "architect"

        # App with sm returning None
        app2 = SimpleNamespace(
            agent=SimpleNamespace(role="worker"),
            role="worker",
            sm=SimpleNamespace(get=MagicMock(return_value=None)),
            current_session_id="sess-1",
            refresh_status_footer=MagicMock(),
        )
        with patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_registry):
            toggle_agent_role(app2)
        assert app2.role == "architect"

        # App with session but without save_current_session method
        session = SimpleNamespace(role="worker")
        app3 = SimpleNamespace(
            agent=SimpleNamespace(role="worker"),
            role="worker",
            sm=SimpleNamespace(get=MagicMock(return_value=session)),
            current_session_id="sess-1",
            refresh_status_footer=MagicMock(),
        )
        with patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_registry):
            toggle_agent_role(app3)
        assert app3.role == "architect"
        assert session.role == "architect"

    def test_reconcile_active_agent_with_recreate_active_agent(self):
        new_agent = SimpleNamespace(history=[], role="worker")
        pm = SimpleNamespace(
            recreate_active_agent=MagicMock(return_value=new_agent),
        )
        app = SimpleNamespace(
            agent=SimpleNamespace(history=[{"msg": 1}], role="architect"),
            role="architect",
            pm=pm,
            refresh_status_footer=MagicMock(),
        )

        result = reconcile_active_agent(app, provider_key="openai")
        assert result is new_agent
        assert result.app is app
        assert app.agent is new_agent
        assert app.role == "architect"
        pm.recreate_active_agent.assert_called_once_with(
            provider_key="openai", history=[{"msg": 1}], role="architect"
        )
        app.refresh_status_footer.assert_called_once()

    def test_reconcile_active_agent_with_recreate_type_error_fallback(self):
        new_agent = SimpleNamespace()
        pm = MagicMock()
        pm.recreate_active_agent.side_effect = [TypeError("signature mismatch"), new_agent]
        app = SimpleNamespace(
            agent=SimpleNamespace(history=[]),
            role="worker",
            pm=pm,
        )

        result = reconcile_active_agent(app, provider_key="anthropic")
        assert result is new_agent
        assert pm.recreate_active_agent.call_count == 2
        pm.recreate_active_agent.assert_called_with(app, provider_key="anthropic")

    def test_reconcile_active_agent_with_create_active_agent(self):
        new_agent = SimpleNamespace(history=[])
        pm = SimpleNamespace(
            set_active_provider_key=MagicMock(),
            create_active_agent=MagicMock(return_value=new_agent),
        )
        app = SimpleNamespace(
            agent=None,
            role="worker",
            pm=pm,
        )

        result = reconcile_active_agent(app, provider_key="gemini", history=["hist1"])
        assert result is new_agent
        pm.set_active_provider_key.assert_called_once_with("gemini")
        pm.create_active_agent.assert_called_once()
        assert new_agent.history == ["hist1"]
        assert new_agent.role == "worker"

    def test_reconcile_active_agent_create_agent_returns_none(self):
        pm = SimpleNamespace(
            create_active_agent=MagicMock(return_value=None),
        )
        app = SimpleNamespace(
            agent=None,
            pm=pm,
        )
        result = reconcile_active_agent(app)
        assert result is None
        assert app.role == "worker"

    def test_reconcile_active_agent_pm_none(self):
        app = SimpleNamespace(
            agent=None,
            role="custom_role",
            pm=None,
        )
        result = reconcile_active_agent(app)
        assert result is None
        assert app.role == "custom_role"


# ============================================================================
# dispatch.py tests
# ============================================================================


class TestDispatchCoverage:
    def test_resolve_skills(self):
        skill_a = SimpleNamespace(name="skill_a")
        sm = MagicMock()
        sm.get_skill.side_effect = lambda name: skill_a if name == "skill_a" else None

        # Duplicate skill_a in request to cover deduplication branch
        loaded, unresolved = _resolve_skills(sm, ["skill_a", "skill_a", "skill_b"])
        assert loaded == [skill_a]
        assert unresolved == ["skill_b"]

    def test_load_skill_blocks_with_content(self):
        skill = SimpleNamespace(name="my-skill", content="Direct content", location="/path/to/skill.md")
        blocks = _load_skill_blocks([skill])
        assert len(blocks) == 1
        assert '<skill name="my-skill" path="/path/to/skill.md">' in blocks[0]
        assert "Direct content" in blocks[0]

    def test_load_skill_blocks_read_file(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\nname: disk-skill\ndescription: test\n---\nBody from file.", encoding="utf-8")

        skill = SimpleNamespace(name="disk-skill", content="", location=str(skill_file))
        blocks = _load_skill_blocks([skill])
        assert len(blocks) == 1
        assert '<skill name="disk-skill"' in blocks[0]
        assert "Body from file." in blocks[0]

    def test_load_skill_blocks_read_file_error_fallback(self, tmp_path):
        # File path that does not exist or raises error
        skill = SimpleNamespace(name="bad-skill", content="", location=str(tmp_path / "nonexistent.md"))
        blocks = _load_skill_blocks([skill])
        assert len(blocks) == 1
        assert '<skill name="bad-skill"' in blocks[0]
        assert "<skill" in blocks[0] and "</skill>" in blocks[0]

        # File exists but parse frontmatter fails
        bad_file = tmp_path / "corrupt.md"
        bad_file.write_text("plain", encoding="utf-8")
        with patch("core.infrastructure.runtime.frontmatter.parse_frontmatter", side_effect=Exception("parse error")):
            blocks2 = _load_skill_blocks([SimpleNamespace(name="corrupt", content="", location=str(bad_file))])
            assert len(blocks2) == 1
            assert '<skill name="corrupt"' in blocks2[0]

    def test_load_skill_blocks_no_location(self):
        skill = SimpleNamespace(name=None, content="some content", location=None)
        blocks = _load_skill_blocks([skill])
        assert len(blocks) == 1
        assert '<skill name="">\nsome content\n</skill>' == blocks[0]

    def test_build_command_registry(self):
        registry = build_command_registry()
        assert isinstance(registry, dict)
        # Should contain at least common commands like /help or /clear
        assert "/help" in registry or "/clear" in registry or len(registry) > 0

    @pytest.mark.asyncio
    async def test_handle_slash_command_empty_or_none(self):
        app = SimpleNamespace()
        assert await handle_slash_command(app, "") is False
        assert await handle_slash_command(app, None) is False  # type: ignore
        assert await handle_slash_command(app, "   ") is False

    @pytest.mark.asyncio
    async def test_handle_slash_command_registered_command(self):
        mock_ci = MagicMock()
        app = SimpleNamespace(query_one=MagicMock(return_value=mock_ci))
        mock_cmd_cls = MagicMock()
        mock_cmd_instance = MagicMock()
        mock_cmd_instance.execute = AsyncMock()
        mock_cmd_cls.return_value = mock_cmd_instance

        with patch.dict("widgets.app.dispatch.COMMAND_REGISTRY", {"/mock": mock_cmd_cls}, clear=False):
            res = await handle_slash_command(app, "/mock arg1 arg2", attachments=["img.png"])
            assert res is True
            mock_cmd_cls.assert_called_once()
            mock_cmd_instance.execute.assert_awaited_once_with(app)
            assert mock_ci.clipboard_attachments == ["img.png"]
            mock_ci.update_attachment_bar.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_slash_command_registered_with_cyrillic_homoglyphs(self):
        app = SimpleNamespace()
        mock_cmd_cls = MagicMock()
        mock_cmd_instance = MagicMock()
        mock_cmd_instance.execute = AsyncMock()
        mock_cmd_cls.return_value = mock_cmd_instance

        # Test Cyrillic 'с' (U+0441) mapping to Latin 'c' -> "/clear"
        with patch.dict("widgets.app.dispatch.COMMAND_REGISTRY", {"/clear": mock_cmd_cls}, clear=False):
            res = await handle_slash_command(app, "/сlear")
            assert res is True
            mock_cmd_instance.execute.assert_awaited_once_with(app)

    @pytest.mark.asyncio
    async def test_handle_slash_command_skills_with_user_request(self):
        app = SimpleNamespace(trigger_ai_response=MagicMock())
        skill = SimpleNamespace(name="my-skill", content="Instruction body", location="")

        with patch("widgets.app.dispatch.get_skill_manager") as mock_sm_get:
            sm = MagicMock()
            sm.get_skill.side_effect = lambda name: skill if name == "my-skill" else None
            mock_sm_get.return_value = sm

            res = await handle_slash_command(app, "/my-skill please review this code /unknown-skill")
            assert res is True
            app.trigger_ai_response.assert_called_once()
            call_args = app.trigger_ai_response.call_args
            prompt = call_args[0][0]
            assert '<skill name="my-skill">' in prompt
            assert "please review this code /unknown-skill" in prompt
            assert call_args[1]["show_in_ui"] is True
            assert call_args[1]["display_text"] == "/my-skill please review this code /unknown-skill"

    @pytest.mark.asyncio
    async def test_handle_slash_command_skills_without_user_request(self):
        app = SimpleNamespace(trigger_ai_response=MagicMock())
        skill = SimpleNamespace(name="solo-skill", content="Solo content", location="")

        with patch("widgets.app.dispatch.get_skill_manager") as mock_sm_get:
            sm = MagicMock()
            sm.get_skill.return_value = skill
            mock_sm_get.return_value = sm

            res = await handle_slash_command(app, "/solo-skill")
            assert res is True
            app.trigger_ai_response.assert_called_once()
            prompt = app.trigger_ai_response.call_args[0][0]
            assert prompt == '<skill name="solo-skill">\nSolo content\n</skill>'

    @pytest.mark.asyncio
    async def test_handle_slash_command_mcp_prompt_fallback(self):
        app = SimpleNamespace(trigger_ai_response=MagicMock())
        mock_mm = MagicMock()
        mock_mm.get_prompt_async = AsyncMock(
            return_value={
                "messages": [
                    {"content": "string content"},
                    {"content": {"type": "text", "text": "dict text content"}},
                    {"content": {"type": "image", "data": "binary"}},
                    {
                        "content": [
                            {"type": "text", "text": "list text content"},
                            {"type": "other", "raw": 123},
                            "nested plain string",
                        ]
                    },
                ]
            }
        )

        with patch("widgets.app.dispatch.get_skill_manager") as mock_sm_get, patch(
            "core.infrastructure.mcp.get_mcp_manager", return_value=mock_mm
        ):
            mock_sm_get.return_value.get_skill.return_value = None

            res = await handle_slash_command(app, "/myserver__custom-prompt topic=AI extra notes")
            assert res is True
            mock_mm.get_prompt_async.assert_awaited_once_with(
                "custom-prompt", arguments={"topic": "AI"}, server_name="myserver"
            )
            app.trigger_ai_response.assert_called_once()
            prompt = app.trigger_ai_response.call_args[0][0]
            assert "string content" in prompt
            assert "dict text content" in prompt
            assert "list text content" in prompt
            assert "extra notes" in prompt

    @pytest.mark.asyncio
    async def test_handle_slash_command_mcp_prompt_empty_messages(self):
        app = SimpleNamespace(trigger_ai_response=MagicMock())
        mock_mm = MagicMock()
        mock_mm.get_prompt_async = AsyncMock(return_value={"messages": []})

        with patch("widgets.app.dispatch.get_skill_manager") as mock_sm_get, patch(
            "core.infrastructure.mcp.get_mcp_manager", return_value=mock_mm
        ):
            mock_sm_get.return_value.get_skill.return_value = None

            res = await handle_slash_command(app, "/mcp-empty")
            assert res is False
            app.trigger_ai_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_slash_command_mcp_exception(self):
        app = SimpleNamespace(trigger_ai_response=MagicMock())

        with patch("widgets.app.dispatch.get_skill_manager") as mock_sm_get, patch(
            "core.infrastructure.mcp.get_mcp_manager", side_effect=RuntimeError("MCP failed")
        ):
            mock_sm_get.return_value.get_skill.return_value = None

            res = await handle_slash_command(app, "/mcp-error")
            assert res is False

    @pytest.mark.asyncio
    async def test_handle_slash_command_non_slash_text(self):
        app = SimpleNamespace(trigger_ai_response=MagicMock())
        with patch("widgets.app.dispatch.get_skill_manager") as mock_sm_get:
            mock_sm_get.return_value.get_skill.return_value = None
            res = await handle_slash_command(app, "regular chat message")
            assert res is False


# ============================================================================
# command_provider.py tests
# ============================================================================


class TestCommandProviderCoverage:
    def test_build_command_suggestions_all_sources(self):
        # Mock COMMAND_REGISTRY
        mock_cmd = SimpleNamespace(name="/help", description="Show help")
        mock_registry = {
            "/help": mock_cmd,
            "/h": mock_cmd,  # alias
        }

        # Mock Skills
        skill1 = SimpleNamespace(name="git", description="Git assistant")
        skill2 = SimpleNamespace(name="code", description="")
        skill3 = SimpleNamespace(name="help", description="Duplicated skill")  # /help already in registry

        mock_sm = MagicMock()
        mock_sm.list_skills.return_value = [skill1, skill2, skill3]

        # Mock MCP
        client = SimpleNamespace(
            prompts=[
                {"name": "review", "description": "Review code"},
                {"name": "no_desc"},
                {"name": ""},  # empty name, should skip
                {"name": "help"},  # already registered /help, should namespace /srv__help
            ]
        )
        mock_mm = SimpleNamespace(clients={"srv": client})

        with patch.dict("widgets.app.command_provider.COMMAND_REGISTRY", mock_registry, clear=True), patch(
            "widgets.app.command_provider.get_skill_manager", return_value=mock_sm
        ), patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mm):
            suggestions = _build_command_suggestions()

        cmds = [s[0] for s in suggestions]
        assert "/help" in cmds
        assert "/h" in cmds
        assert "/git" in cmds
        assert "/code" in cmds
        assert "/review" in cmds
        assert "/no_desc" in cmds
        assert "/srv__help" in cmds

        # Check descriptions
        desc_map = dict(suggestions)
        assert desc_map["/help"] == "Show help"
        assert desc_map["/h"] == "Alias for /help"
        assert desc_map["/git"] == "Skill: Git assistant"
        assert desc_map["/code"] == "Skill: code"
        assert desc_map["/review"] == "MCP Prompt [srv]: Review code"
        assert desc_map["/no_desc"] == "MCP Prompt [srv]: MCP Prompt (srv)"
        assert desc_map["/srv__help"] == "MCP Prompt [srv]: MCP Prompt (srv)"

    def test_build_command_suggestions_with_exceptions(self):
        mock_registry = {"/cmd": SimpleNamespace(name="/cmd", description="desc")}

        with patch.dict("widgets.app.command_provider.COMMAND_REGISTRY", mock_registry, clear=True), patch(
            "widgets.app.command_provider.get_skill_manager", side_effect=Exception("skill manager error")
        ), patch("core.infrastructure.mcp.get_mcp_manager", side_effect=Exception("mcp error")):
            suggestions = _build_command_suggestions()

        assert len(suggestions) == 1
        assert suggestions[0] == ("/cmd", "desc")

    @pytest.mark.asyncio
    async def test_get_all_command_suggestions_caching(self):
        import widgets.app.command_provider as cp

        cp._command_suggestions_cache = []
        cp._command_suggestions_cache_time = 0.0

        sample_suggestions = [("/test", "Test description")]
        try:
            with patch("widgets.app.command_provider._build_command_suggestions", return_value=sample_suggestions) as mock_b:
                res1 = await get_all_command_suggestions()
                assert res1 == sample_suggestions
                assert mock_b.call_count == 1

                # Call again within 10s -> cache hit
                res2 = await get_all_command_suggestions()
                assert res2 == sample_suggestions
                assert mock_b.call_count == 1

                # Advance time by 15s -> cache expired, re-called
                with patch("widgets.app.command_provider.time.time", return_value=cp._command_suggestions_cache_time + 15.0):
                    res3 = await get_all_command_suggestions()
                    assert res3 == sample_suggestions
                    assert mock_b.call_count == 2
        finally:
            cp._command_suggestions_cache = []
            cp._command_suggestions_cache_time = 0.0
