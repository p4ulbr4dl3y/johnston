import asyncio
import logging
import os
from typing import Any

from core.models_catalog import catalog
from core.skill_manager import SkillManager
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.modal_screens import (
    HelpScreen,
    LintersScreen,
    MCPScreen,
    ModelScreen,
    ResumeScreen,
    RewindScreen,
    SkillsScreen,
    SubagentsScreen,
    ThinkingEffortScreen,
)
from widgets.screens.constants import MESSAGE_INPUT

logger = logging.getLogger(__name__)


class BaseCommand:
    """Base class for slash commands"""

    name: str = ""
    description: str = ""

    async def execute(self, app) -> None:
        raise NotImplementedError


class HelpCommand(BaseCommand):
    name = "/help"
    aliases = ["/h", "/?"]
    description = "Show help and keybindings"

    async def execute(self, app) -> None:
        app.push_screen(HelpScreen())


class NewCommand(BaseCommand):
    name = "/new"
    aliases = ["/clear", "/reset"]
    description = "Start a new chat session"

    async def execute(self, app) -> None:
        for w in [w for w in getattr(app, "workers", []) if w.is_running]:
            w.cancel()
        from core.background_task import kill_all_background_tasks

        kill_all_background_tasks(getattr(app, "background_tasks", []))
        if hasattr(app, "background_tasks"):
            app.background_tasks.clear()
        from core.subagent_stream import cancel_running_subagents

        cancel_running_subagents(app.sm)
        # Reset generation state synchronously: cancelled workers clear is_generating
        # in their own finally, but that runs asynchronously, so /new could leave the
        # app stuck "generating" and swallow subsequent input into the queue.
        app.is_generating = False
        app.message_queue.clear()
        app.current_session_id = app.sm.generate_session_id()
        app.sm.create_main(app.current_session_id)
        chat_view = app.query_one(ChatView)
        await chat_view.remove_children()
        chat_view.check_welcome()
        app.agent.clear_history()
        app.refresh_status_footer()


class ProvidersCommand(BaseCommand):
    name = "/providers"
    aliases = ["/connect", "/provider"]
    description = "Manage AI providers (API keys, active status, enable/disable)"

    async def execute(self, app) -> None:
        from widgets.screens.providers import ApiKeyInputScreen, ProvidersScreen

        def open_providers_screen(focus_key: str | None = None) -> None:
            provs = app.pm.load_providers(include_disabled=True)
            if not provs:
                app.notify("No available providers configured", severity="warning")
                return

            act_key = focus_key or app.pm.get_active_provider_key()
            cfg_keys = {k: app.pm.get_api_key(k) for k in provs}
            dis_provs = app.pm.get_disabled_providers()

            def on_provider_selected(selected_key: str | None) -> None:
                if not selected_key:
                    app.query_one(MESSAGE_INPUT, ChatInput).focus()
                    return

                p_info = provs.get(selected_key, {})
                p_name = p_info.get("name", selected_key)
                curr_key = app.pm.get_api_key(selected_key)

                def on_key_entered(entered_key: str | None) -> None:
                    if entered_key is not None:
                        if entered_key:
                            app.pm.set_provider_api_key(selected_key, entered_key)
                            app.pm.set_provider_disabled(selected_key, False)
                        app.pm.recreate_active_agent(app, provider_key=selected_key)
                        if entered_key:
                            asyncio.create_task(ModelsCommand().execute(app))
                        else:
                            open_providers_screen(focus_key=selected_key)

                app.push_screen(ApiKeyInputScreen(p_name, selected_key, curr_key), callback=on_key_entered)

            app.push_screen(
                ProvidersScreen(
                    provs,
                    act_key,
                    cfg_keys,
                    disabled_providers=dis_provs,
                    pm=app.pm,
                ),
                callback=on_provider_selected,
            )

        open_providers_screen()


class ModelsCommand(BaseCommand):
    name = "/models"
    aliases = ["/model"]
    description = "Switch model for providers"

    async def execute(self, app) -> None:
        asyncio.create_task(catalog.refresh())
        grouped_models = await app.pm.fetch_models_grouped()
        if not grouped_models:
            connected = any(app.pm.is_provider_connected(k, v) for k, v in app.pm.load_providers().items())
            if not connected:
                await ProvidersCommand().execute(app)
                return
            app.notify("Failed to fetch models: check API key or network connection", severity="warning")
            return

        curr_provider = app.pm.get_active_provider_key()
        curr_model = getattr(app.agent, "model", "") if getattr(app, "agent", None) else ""
        if not curr_model and hasattr(app.pm, "get_provider_model"):
            curr_model = app.pm.get_provider_model(curr_provider)

        def on_model_selected(selection: Any) -> None:
            if selection:
                item_val = selection

                if isinstance(item_val, (tuple, list)):
                    selected_prov, selected_model = item_val[0], item_val[1]
                else:
                    selected_prov = curr_provider
                    selected_model = item_val

                if selected_prov != app.pm.get_active_provider_key():
                    app.pm.recreate_active_agent(app, provider_key=selected_prov)

                if hasattr(app.agent, "model"):
                    app.agent.model = selected_model
                app.pm.set_provider_model(selected_prov, selected_model)
                app.refresh_status_footer()
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        app.push_screen(ModelScreen(grouped_models, curr_model, curr_provider), callback=on_model_selected)


class ThinkingEffortCommand(BaseCommand):
    name = "/thinking"
    aliases = ["/effort", "/reasoning"]
    description = "Set thinking effort for the active provider/model"

    async def execute(self, app) -> None:
        if not getattr(app, "pm", None):
            app.notify("Provider manager not available", severity="warning")
            return

        provider_key = app.pm.get_active_provider_key()
        model_name = getattr(getattr(app, "agent", None), "model", "") or app.pm.get_provider_model(provider_key)
        current_effort = ""
        if hasattr(app.pm, "get_provider_thinking_effort"):
            current_effort = app.pm.get_provider_thinking_effort(provider_key, model_name)

        def on_effort_selected(effort: str):
            if not effort:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            if hasattr(app.pm, "set_provider_thinking_effort"):
                app.pm.set_provider_thinking_effort(provider_key, model_name, effort)
            app.pm.recreate_active_agent(app)
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        app.push_screen(ThinkingEffortScreen(current_effort), callback=on_effort_selected)


class RewindCommand(BaseCommand):
    name = "/rewind"
    aliases = ["/undo"]
    description = "Rollback chat history to a message"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        user_msgs = chat_view.get_user_messages()
        if not user_msgs:
            app.notify("History is empty: no messages to rollback", severity="warning")
            return

        curr_sid = getattr(app, "current_session_id", None)
        proj_path = getattr(app.sm, "project_path", None) if hasattr(app, "sm") else None
        msgs_with_stats = []
        checkpoints_enabled = False

        try:
            from core.git_checkpoint import GitCheckpointManager

            checkpoints_enabled = await asyncio.to_thread(GitCheckpointManager.is_valid_checkpoint_target, proj_path)
            if curr_sid and checkpoints_enabled:
                seq_indices = list(range(len(user_msgs)))
                try:
                    stats_map = await asyncio.wait_for(
                        asyncio.to_thread(
                            GitCheckpointManager.get_diff_stats_batch,
                            curr_sid,
                            seq_indices,
                            project_path=proj_path,
                        ),
                        timeout=2.0,
                    )
                except (asyncio.TimeoutError, Exception):
                    stats_map = {}
                for seq_idx, (child_idx, text) in enumerate(user_msgs):
                    stat = stats_map.get(seq_idx) or ""
                    msgs_with_stats.append((child_idx, text, stat))
            else:
                msgs_with_stats = [(child_idx, text, "") for child_idx, text in user_msgs]
        except Exception:
            msgs_with_stats = [(child_idx, text, "") for child_idx, text in user_msgs]

        def on_rewind_selected(selected_idx: int | None) -> None:
            if selected_idx is not None and selected_idx >= 0:
                # Find original text and sequence index of message being rolled back to
                msg_text = ""
                seq_idx = 0
                for i, (child_idx, text) in enumerate(user_msgs):
                    if child_idx == selected_idx:
                        msg_text = text
                        seq_idx = i
                        break

                # Rollback chat to position immediately preceding selected message
                target_idx = selected_idx - 1
                chat_view.rollback_to(target_idx)

                if seq_idx == 0:
                    if hasattr(app.agent, "clear_history"):
                        app.agent.clear_history()
                    elif hasattr(app.agent, "history"):
                        app.agent.history = []
                    for attr, value in (
                        ("tokens_input", 0),
                        ("tokens_output", 0),
                        ("tokens_cache_read", 0),
                        ("last_context_tokens", 0),
                        ("total_tokens", 0),
                        ("cost_usd", 0.0),
                    ):
                        if hasattr(app.agent, attr):
                            setattr(app.agent, attr, value)
                else:
                    if hasattr(app.agent, "truncate_history_to_user_message"):
                        app.agent.truncate_history_to_user_message(seq_idx)
                    elif hasattr(app.agent, "history"):
                        app.agent.history = []

                # Restore Git checkpoint state if available
                if curr_sid:

                    async def _restore_git_bg():
                        try:
                            from core.git_checkpoint import GitCheckpointManager

                            await asyncio.to_thread(
                                GitCheckpointManager.restore_checkpoint, curr_sid, seq_idx, project_path=proj_path
                            )
                            await asyncio.to_thread(
                                GitCheckpointManager.purge_checkpoints_after, curr_sid, seq_idx, project_path=proj_path
                            )
                        except Exception as e:
                            logger.warning("Git checkpoint restore failed: %s", e)

                    asyncio.create_task(_restore_git_bg())

                app.refresh_status_footer()
                if hasattr(app, "save_current_session_async"):
                    asyncio.create_task(app.save_current_session_async())
                else:
                    app.save_current_session()

                # Load text into input field
                chat_input = app.query_one(MESSAGE_INPUT)
                chat_input.load_text(msg_text)
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            app.query_one(MESSAGE_INPUT).focus()

        app.push_screen(
            RewindScreen(msgs_with_stats, checkpoints_enabled=checkpoints_enabled), callback=on_rewind_selected
        )


class ResumeCommand(BaseCommand):
    name = "/resume"
    aliases = ["/sessions", "/load"]
    description = "Resume a saved session"

    async def execute(self, app) -> None:
        sessions = app.sm.list_main_sessions()
        if not sessions:
            app.notify("No saved sessions in this project", severity="warning")
            return

        def on_resume_selected(selected_sid: str) -> None:
            if selected_sid:
                app.load_session_ui(selected_sid)
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        app.push_screen(ResumeScreen(sessions), callback=on_resume_selected)


class SubagentsCommand(BaseCommand):
    name = "/subagents"
    aliases = ["/agents", "/subagent"]
    description = "Manage subagents"

    async def execute(self, app) -> None:
        store = getattr(app, "sm", None)
        curr_sid = getattr(app, "current_session_id", None)
        sessions = []
        if store:
            sessions = store.get_subagents_for_parent(curr_sid) if curr_sid else store.list(kind="subagent")

        if not sessions:
            app.notify("No active subagents", severity="warning")
            return
        app.push_screen(SubagentsScreen())


class SkillsCommand(BaseCommand):
    name = "/skills"
    aliases = ["/skill"]
    description = "Browse and activate available skills"

    async def execute(self, app) -> None:
        sm = SkillManager()
        skills = sm.list_skills()
        if not skills:
            app.notify("No available skills found", severity="warning")
            return

        def on_skill_selected(selected_skill: dict | None) -> None:
            chat_input = app.query_one(MESSAGE_INPUT, ChatInput)
            if selected_skill:
                s_name = selected_skill["name"]
                chat_input.load_text(f"/{s_name} ")
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            chat_input.focus()

        app.push_screen(SkillsScreen(), callback=on_skill_selected)


class MCPCommand(BaseCommand):
    name = "/mcp"
    aliases = ["/mcps"]
    description = "Manage MCP servers (toggle enabled/disabled)"

    async def execute(self, app) -> None:
        app.push_screen(MCPScreen())


class LintersCommand(BaseCommand):
    name = "/linters"
    aliases = ["/lint"]
    description = "Manage linters (toggle enabled/disabled, install/uninstall)"

    async def execute(self, app) -> None:
        app.push_screen(LintersScreen())


class CompactCommand(BaseCommand):
    name = "/compact"
    aliases = ["/compress"]
    description = "Compact session conversation history with AI summary"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent found", severity="error")
            return

        if hasattr(app.agent, "compact_history"):
            chat_view = None
            divider = None
            if hasattr(app, "query_one"):
                try:
                    from widgets.chat_view import ChatView

                    cv = app.query_one(ChatView)
                    if cv and hasattr(cv, "add_event_divider"):
                        chat_view = cv
                        divider = await chat_view.add_event_divider("Compacting session...")
                except Exception:
                    pass

            app.is_generating = True
            try:
                success, msg = await app.agent.compact_history()
                if success:
                    title = "Session Compacted"
                    if msg and "(" in msg and ")" in msg:
                        tokens_info = msg[msg.find("(") + 1 : msg.rfind(")")]
                        title = f"Session Compacted ({tokens_info})"

                    if divider and hasattr(divider, "update_title"):
                        divider.update_title(title)
                    elif chat_view and hasattr(chat_view, "add_event_divider"):
                        await chat_view.add_event_divider(title)

                    if hasattr(app, "refresh_status_footer"):
                        app.refresh_status_footer()
                else:
                    if divider and hasattr(divider, "update_title"):
                        divider.update_title(f"Compaction Failed: {msg}")
                    app.notify(msg or "Context compaction failed", severity="warning")
            except asyncio.CancelledError:
                if divider and hasattr(divider, "update_title"):
                    divider.update_title("Compaction Cancelled")
                raise
            finally:
                if hasattr(app, "save_current_session"):
                    try:
                        app.save_current_session()
                    except Exception:
                        pass
                app.is_generating = False
        else:
            app.notify("Active agent does not support context compaction", severity="warning")


class PermissionsCommand(BaseCommand):
    name = "/permissions"
    aliases = ["/permission", "/perms"]
    description = "Manage tool permissions (allow, ask, deny)"

    async def execute(self, app) -> None:
        from widgets.screens.permissions import PermissionsScreen

        app.push_screen(PermissionsScreen())


class QuestionsCommand(BaseCommand):
    name = "/questions"
    aliases = ["/q", "/ask"]
    description = "Resume pending user questions wizard"

    async def execute(self, app) -> None:
        from widgets.screens.ask_user import AskUserWizardScreen

        if hasattr(app, "screen") and isinstance(app.screen, AskUserWizardScreen):
            if hasattr(app, "notify"):
                app.notify("Question wizard is currently active", severity="info")
            return

        pending_func = getattr(app, "_pending_ask_user", None)
        if callable(pending_func):
            pending_func()
        else:
            if hasattr(app, "notify"):
                app.notify("No pending questions", severity="warning")


COMMAND_CLASSES = [
    HelpCommand,
    NewCommand,
    ProvidersCommand,
    ModelsCommand,
    ThinkingEffortCommand,
    RewindCommand,
    ResumeCommand,
    SubagentsCommand,
    SkillsCommand,
    MCPCommand,
    LintersCommand,
    CompactCommand,
    PermissionsCommand,
    QuestionsCommand,
]


COMMAND_REGISTRY = {}
for cls in COMMAND_CLASSES:
    COMMAND_REGISTRY[cls.name] = cls
    for alias in getattr(cls, "aliases", []):
        COMMAND_REGISTRY[alias] = cls


async def handle_slash_command(app, command_text: str) -> bool:
    """Executes command if registered or skill found. Returns True if handled."""
    if not command_text:
        return False
    words = command_text.strip().split()
    if not words:
        return False

    cmd_name = words[0].lower()

    # Normalization of Cyrillic homoglyphs to Latin (to handle layout errors)
    homoglyphs = {
        "а": "a",
        "в": "b",
        "е": "e",
        "к": "k",
        "м": "m",
        "н": "h",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "у": "y",
        "х": "x",
    }
    normalized_name = "".join(homoglyphs.get(c, c) for c in cmd_name)

    if command_text.strip().startswith("/") and normalized_name in COMMAND_REGISTRY:
        cmd_instance = COMMAND_REGISTRY[normalized_name]()
        try:
            await cmd_instance.execute(app, args=words[1:])
        except TypeError:
            await cmd_instance.execute(app)
        return True

    # Multi-skill & single-skill slash command execution (e.g. /johnston-guide /caveman request)
    words = command_text.strip().split()
    sm = SkillManager()
    loaded_skills = []
    other_words = []

    for w in words:
        if w.startswith("/"):
            raw_sname = w[1:].lower()
            norm_sname = "".join(homoglyphs.get(c, c) for c in raw_sname)
            skill = sm.get_skill(norm_sname)
            if skill:
                if skill not in loaded_skills:
                    loaded_skills.append(skill)
            else:
                other_words.append(w)
        else:
            other_words.append(w)

    if loaded_skills:
        skill_blocks = []
        for s in loaded_skills:
            content = s.get("content", "").strip()
            if not content and s.get("location") and os.path.exists(s["location"]):
                try:
                    with open(s["location"], "r", encoding="utf-8") as f:
                        raw_c = f.read()
                    from core.skill_manager import parse_frontmatter

                    _, body = parse_frontmatter(raw_c)
                    content = body.strip()
                except Exception:
                    content = ""
            skill_blocks.append(f'<SKILL path="{s.get("location", "")}">\n{content}\n</SKILL>')

        skills_content = "\n\n".join(skill_blocks)
        user_request = " ".join(other_words).strip()
        if user_request:
            prompt = f"The following skill(s) have been invoked:\n\n{skills_content}\n\nUser request: {user_request}"
        else:
            prompt = f"The following skill(s) have been invoked:\n\n{skills_content}"

        try:
            from widgets.chat_view import ChatView

            chat_view = app.query_one(ChatView)

            asyncio.create_task(chat_view.add_user_message(command_text))
            app.trigger_ai_response(prompt, show_in_ui=False)
        except Exception:
            app.trigger_ai_response(prompt, show_in_ui=True)
        return True

    return False
