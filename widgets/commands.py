import asyncio
import logging
from typing import Any

from core.application.provider.actions import (
    fetch_api_key_and_provider_info,
    fetch_grouped_models,
    get_current_thinking_effort,
    select_model,
    set_provider_credentials,
    set_thinking_effort,
)
from core.application.session.actions import (
    compact_session,
    get_rewind_git_stats,
    new_session,
    resume_session,
    rewind_session,
)
from core.application.skills.manager import SkillManager
from core.models_catalog import catalog
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.modal_screens import (
    HelpScreen,
    MCPScreen,
    ModelScreen,
    ResumeScreen,
    RewindScreen,
    ShellTasksScreen,
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
        def cancel_workers():
            for w in [w for w in getattr(app, "workers", []) if w.is_running]:
                w.cancel()

        async def kill_all_tasks():
            await app.task_manager.kill_all()

        def cancel_subagents():
            from core.application.session.stream import cancel_running_subagents
            cancel_running_subagents(app.sm)

        new_id = await new_session(
            app.sm, app.agent,
            cancel_workers=cancel_workers, kill_all_tasks=kill_all_tasks, cancel_subagents=cancel_subagents,
        )

        # UI state
        app.is_generating = False
        app.message_queue.clear()
        app.current_session_id = new_id

        # UI: clear chat view, show welcome, refresh footer
        chat_view = app.query_one(ChatView)
        await chat_view.remove_children()
        chat_view.check_welcome()
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

                p_name, curr_key = fetch_api_key_and_provider_info(app.pm, selected_key)

                def on_key_entered(entered_key: str | None) -> None:
                    if entered_key is not None:
                        fetched = set_provider_credentials(app.pm, selected_key, entered_key, app)
                        if fetched:
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
        grouped_models, is_disconnected = await fetch_grouped_models(app.pm)
        if not grouped_models:
            if is_disconnected:
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

                select_model(app.pm, app.agent, selected_prov, selected_model, app)
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

        provider_key, model_name, current_effort = get_current_thinking_effort(app.pm, app.agent)

        def on_effort_selected(effort: str):
            if not effort:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            set_thinking_effort(app.pm, provider_key, model_name, effort, app)
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
        msgs_with_stats = await get_rewind_git_stats(curr_sid, user_msgs, proj_path)
        checkpoints_enabled = any(stat for _, _, stat in msgs_with_stats)

        def on_rewind_selected(selected_idx: int | None) -> None:
            if selected_idx is not None and selected_idx >= 0:
                def rollback_ui(target_idx: int) -> None:
                    chat_view.rollback_to(target_idx)

                def load_text_into_input(text: str) -> None:
                    chat_input = app.query_one(MESSAGE_INPUT)
                    chat_input.load_text(text)
                    lines = chat_input.text.split("\n")
                    chat_input.move_cursor((len(lines) - 1, len(lines[-1])))

                def save_cb() -> None:
                    if hasattr(app, "save_current_session_async"):
                        asyncio.create_task(app.save_current_session_async())
                    else:
                        app.save_current_session()

                rewind_session(
                    app.agent,
                    curr_sid,
                    proj_path,
                    user_msgs,
                    selected_idx,
                    rollback_ui=rollback_ui,
                    load_text_into_input=load_text_into_input,
                    save_session_cb=save_cb,
                    refresh_footer_cb=lambda: app.refresh_status_footer(),
                )
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
                resume_session(app.sm, selected_sid)
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
        has_sessions = bool(
            store and (store.get_subagents_for_parent(curr_sid) if curr_sid else store.list(kind="subagent"))
        )

        if not has_sessions:
            app.notify("No active subagents", severity="warning")
            return
        app.push_screen(SubagentsScreen())


class ShellTasksCommand(BaseCommand):
    name = "/shell"
    aliases = ["/shelltasks"]
    description = "Manage background shell tasks"

    async def execute(self, app) -> None:
        all_tasks = getattr(app, "task_manager", [])
        curr_sid = getattr(app, "current_session_id", None)
        has_tasks = bool(
            any(
                getattr(t, "kind", "") == "shell"
                and getattr(t, "is_background", False)
                and (getattr(t, "session_id", None) == curr_sid if curr_sid else True)
                for t in all_tasks
            )
        )

        if not has_tasks:
            app.notify("No active shell tasks", severity="warning")
            return
        app.push_screen(ShellTasksScreen())


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


class CompactCommand(BaseCommand):
    name = "/compact"
    aliases = ["/compress"]
    description = "Compact session conversation history with AI summary"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent found", severity="error")
            return

        divider = None

        # UI setup: create the "Compacting..." divider
        if hasattr(app, "query_one"):
            try:
                cv = app.query_one(ChatView)
                if cv and hasattr(cv, "add_event_divider"):
                    divider = await cv.add_event_divider("Compacting session...")
            except Exception:
                pass

        def save_cb() -> None:
            if hasattr(app, "save_current_session"):
                try:
                    app.save_current_session()
                except Exception:
                    pass

        def on_begin() -> None:
            app.is_generating = True

        def on_divider_update(title: str) -> None:
            nonlocal divider
            if divider and hasattr(divider, "update_title"):
                divider.update_title(title)

        success, msg = await compact_session(
            app.agent,
            save_session_cb=save_cb,
            on_begin=on_begin,
            on_divider_update=on_divider_update,
            refresh_footer_cb=lambda: app.refresh_status_footer(),
        )
        if not success:
            app.notify(msg or "Context compaction failed", severity="warning")


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
    ShellTasksCommand,
    SkillsCommand,
    MCPCommand,
    CompactCommand,
    PermissionsCommand,
    QuestionsCommand,
]


# Registry building + dispatch now live in widgets.app.dispatch, keyed off
# COMMAND_CLASSES above. Re-export the registry and handler for back-compat.
from widgets.app.dispatch import (  # noqa: E402, F401
    COMMAND_REGISTRY,
    build_command_registry,
    handle_slash_command,
)
