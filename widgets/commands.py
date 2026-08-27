import asyncio
import logging
from typing import Any

from core.application.provider.actions import (
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
    rewind_session,
)
from core.application.skills.manager import get_skill_manager
from core.infrastructure.mcp import get_mcp_manager
from core.models_catalog import catalog
from widgets.chat_input import ChatInput
from widgets.presentation.screens.constants import MESSAGE_INPUT
from widgets.presentation.screens.fork import FORK_CURRENT_STATE, ForkScreen
from widgets.presentation.screens.help import HelpScreen
from widgets.presentation.screens.mcp import MCPScreen
from widgets.presentation.screens.model import ModelScreen
from widgets.presentation.screens.rename_session import RenameSessionScreen
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.rewind import RewindScreen, RewindSelection
from widgets.presentation.screens.skills import SkillsScreen
from widgets.presentation.screens.tasks import ShellTasksScreen, SubagentsScreen
from widgets.presentation.screens.thinking_effort import ThinkingEffortScreen
from widgets.presentation.widgets.chat_container import ChatView

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

        old_id = getattr(app, "current_session_id", None)
        if old_id and hasattr(app.sm, "release_session_lock"):
            app.sm.release_session_lock(old_id)

        new_id = await new_session(
            app.sm, app.agent,
            cancel_workers=cancel_workers, kill_all_tasks=kill_all_tasks, cancel_subagents=cancel_subagents,
        )

        if hasattr(app.sm, "acquire_session_lock"):
            app.sm.acquire_session_lock(new_id)

        # UI state
        app.is_generating = False
        app.is_read_only = False
        app.message_queue.clear()
        app.current_session_id = new_id
        app.role = getattr(app.agent, "role", "worker") if app.agent else "worker"

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
        from widgets.presentation.screens.providers import ProvidersScreen

        try:
            provs = await asyncio.to_thread(app.pm.load_providers, True)
        except Exception:
            provs = {}
        if not provs:
            app.notify("No available providers configured", severity="warning")
            return

        def _load_cfg() -> tuple:
            act_key = app.pm.get_active_provider_key()
            cfg_keys = {k: app.pm.get_api_key(k) for k in provs}
            dis_provs = app.pm.get_disabled_providers()
            return act_key, cfg_keys, dis_provs

        act_key, cfg_keys, dis_provs = await asyncio.to_thread(_load_cfg)

        def on_provider_selected(result: tuple[str, str] | str | None) -> None:
            if not result:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            if isinstance(result, tuple):
                selected_key, entered_key = result
            elif isinstance(result, str):
                selected_key, entered_key = result, ""
            else:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            if entered_key is not None:
                fetched = set_provider_credentials(app.pm, selected_key, entered_key, app)
                if fetched:
                    asyncio.create_task(ModelsCommand().execute(app))
                else:
                    open_providers_screen(focus_key=selected_key)

        def open_providers_screen(focus_key: str | None = None) -> None:
            if focus_key:
                asyncio.create_task(
                    ProvidersCommand()._open_with_key(app, focus_key, on_provider_selected)
                )
                return
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

    async def _open_with_key(self, app, focus_key, on_provider_selected) -> None:
        from widgets.presentation.screens.providers import ProvidersScreen

        try:
            provs = await asyncio.to_thread(app.pm.load_providers, True)
        except Exception:
            return
        if not provs:
            app.notify("No available providers configured", severity="warning")
            return
        act_key = app.pm.get_active_provider_key()
        cfg_keys = {k: app.pm.get_api_key(k) for k in provs}
        dis_provs = app.pm.get_disabled_providers()
        app.push_screen(
            ProvidersScreen(
                provs,
                focus_key or act_key,
                cfg_keys,
                disabled_providers=dis_provs,
                pm=app.pm,
            ),
            callback=on_provider_selected,
        )


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

        app.push_screen(ModelScreen(grouped_models, curr_model, curr_provider, pm=app.pm), callback=on_model_selected)


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
        checkpoints_enabled = any(m.git_stats for m in msgs_with_stats)

        async def on_rewind_selected(selection: Any) -> None:
            if selection is None:
                app.query_one(MESSAGE_INPUT).focus()
                return

            if isinstance(selection, RewindSelection):
                selected_idx = selection.index
                restore_code = selection.restore_code
            elif isinstance(selection, int):
                selected_idx = selection
                restore_code = True
            else:
                app.query_one(MESSAGE_INPUT).focus()
                return

            if selected_idx >= 0:
                # 1. Stop in-flight generation first and wait for its cleanup
                #    before touching history/UI, so the engine's interruption
                #    teardown cannot re-pollute the rolled-back state.
                try:
                    for w in [w for w in getattr(app, "workers", []) if w.is_running]:
                        w.cancel()
                except Exception:
                    pass
                try:
                    from textual.worker import WorkerCancelled, WorkerFailed

                    for w in [w for w in getattr(app, "workers", []) if not w.is_finished]:
                        try:
                            await asyncio.wait_for(w.wait(), timeout=1.0)
                        except (WorkerCancelled, WorkerFailed, TimeoutError, asyncio.TimeoutError):
                            pass
                except Exception:
                    pass
                app.is_generating = False
                if hasattr(app, "message_queue"):
                    app.message_queue.clear()

                # 2. Kill background shell tasks and cancel running subagents so
                #    their completion callbacks cannot append results after the
                #    rollback (mirrors NewCommand behaviour).
                try:
                    if hasattr(app, "task_manager"):
                        await app.task_manager.kill_all()
                except Exception:
                    pass
                try:
                    from core.application.session.stream import cancel_running_subagents

                    if getattr(app, "sm", None) is not None:
                        cancel_running_subagents(app.sm, curr_sid)
                except Exception:
                    pass

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

                sm = getattr(app, "sm", None)
                session = sm.get(curr_sid, reload=False) if (sm and curr_sid) else None

                rewind_session(
                    app.agent,
                    curr_sid,
                    proj_path,
                    user_msgs,
                    selected_idx,
                    restore_git=restore_code,
                    session=session,
                    rollback_ui=rollback_ui,
                    load_text_into_input=load_text_into_input,
                    save_session_cb=save_cb,
                    refresh_footer_cb=lambda: app.refresh_status_footer(),
                )
            app.query_one(MESSAGE_INPUT).focus()

        result = app.push_screen(
            RewindScreen(
                msgs_with_stats,
                checkpoints_enabled=checkpoints_enabled,
                session_id=curr_sid,
                project_path=proj_path,
            ),
            callback=on_rewind_selected,
        )
        # Test doubles may return a coroutine for the async callback; the real
        # Textual push_screen is synchronous and returns None.
        if asyncio.iscoroutine(result):
            await result


class ForkCommand(BaseCommand):
    name = "/fork"
    aliases = ["/branch"]
    description = "Fork session from a selected message"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        user_msgs = chat_view.get_user_messages()
        if not user_msgs:
            app.notify("History is empty: no messages to fork", severity="warning")
            return

        curr_sid = getattr(app, "current_session_id", None)
        if not curr_sid or not hasattr(app, "sm"):
            app.notify("No active session to fork", severity="warning")
            return

        def on_fork_selected(selected_child_idx: int | None) -> None:
            if selected_child_idx is None:
                app.query_one(MESSAGE_INPUT).focus()
                return

            if selected_child_idx == FORK_CURRENT_STATE:
                up_to_idx = None
                msg_text = ""
                parent_sess = app.sm.get(curr_sid)
                fork_title = None
                if parent_sess:
                    base = (parent_sess.description or parent_sess.title or "Session").removesuffix(" (fork)")
                    fork_title = f"{base} (fork)"
            else:
                found = False
                msg_text = ""
                seq_idx = 0
                for i, (child_idx, text) in enumerate(user_msgs):
                    if child_idx == selected_child_idx:
                        msg_text = text
                        seq_idx = i
                        found = True
                        break

                if not found:
                    app.query_one(MESSAGE_INPUT).focus()
                    return

                up_to_idx = seq_idx
                fork_title = None
                if seq_idx > 0 and msg_text:
                    clean_msg = " ".join(msg_text.replace("\n", " ").replace("\r", " ").split())
                    if clean_msg:
                        fork_title = clean_msg
                elif seq_idx == 0:
                    parent_sess = app.sm.get(curr_sid)
                    if parent_sess:
                        base = parent_sess.title.removesuffix(" (fork)")
                        fork_title = f"{base} (fork)"

            forked = app.sm.fork_session(curr_sid, new_title=fork_title, up_to_msg_index=up_to_idx)
            if not forked:
                app.notify("Failed to fork session", severity="error")
                app.query_one(MESSAGE_INPUT).focus()
                return

            try:
                if hasattr(app, "workers"):
                    for w in app.workers:
                        if getattr(w, "is_running", False):
                            w.cancel()
            except Exception:
                pass
            # Unlike /new and /rewind, fork deliberately does NOT kill background
            # shell tasks or running subagents: the source session stays resumable
            # and those tasks are app-scoped, so killing them would discard live work.
            app.is_generating = False
            if hasattr(app, "message_queue"):
                app.message_queue.clear()

            app.load_session_ui(forked.id)

            chat_input = app.query_one(MESSAGE_INPUT, ChatInput)
            if msg_text:
                chat_input.load_text(msg_text)
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            else:
                chat_input.load_text("")
            chat_input.focus()
            app.notify("Session forked", severity="info")

        result = app.push_screen(
            ForkScreen(user_msgs),
            callback=on_fork_selected,
        )
        if asyncio.iscoroutine(result):
            await result


class RenameCommand(BaseCommand):
    name = "/rename"
    aliases = ["/title", "/name"]
    description = "Rename the active chat session"

    async def execute(self, app) -> None:
        curr_sid = getattr(app, "current_session_id", None)
        if not curr_sid or not hasattr(app, "sm"):
            app.notify("No active session to rename", severity="warning")
            return

        sess = app.sm.get(curr_sid)
        if not sess:
            try:
                role = getattr(app, "role", "worker") or "worker"
                sess = app.sm.create_main(curr_sid, role=role)
            except Exception:
                sess = None
        if not sess:
            app.notify("Session not found", severity="error")
            return

        current_title = sess.description or sess.title
        if current_title == "Untitled":
            current_title = ""

        def on_renamed(new_title: str | None) -> None:
            if new_title is not None:
                new_title = new_title.strip()
                if new_title:
                    sess.description = new_title
                    if hasattr(app, "agent") and getattr(app.agent, "history", None):
                        sess.agent_history = list(app.agent.history)
                    app.sm.save(sess)
                    if hasattr(app, "refresh_status_footer"):
                        app.refresh_status_footer()
                    app.notify("Session renamed", severity="info")
            app.query_one(MESSAGE_INPUT).focus()

        result = app.push_screen(
            RenameSessionScreen(current_title=current_title),
            callback=on_renamed,
        )
        if asyncio.iscoroutine(result):
            await result


class ResumeCommand(BaseCommand):
    name = "/resume"
    aliases = ["/sessions", "/load"]
    description = "Resume a saved session"

    async def execute(self, app) -> None:
        sessions = await asyncio.to_thread(app.sm.list_main_sessions)
        if not sessions:
            app.notify("No saved sessions in this project", severity="warning")
            return

        def _apply_selected(sid: str, read_only: bool = False) -> None:
            try:
                if hasattr(app, "workers"):
                    for w in app.workers:
                        if getattr(w, "is_running", False):
                            w.cancel()
            except Exception:
                pass
            app.is_generating = False
            if hasattr(app, "message_queue"):
                app.message_queue.clear()
            if read_only:
                app.load_session_ui(sid, read_only=True)
            else:
                app.load_session_ui(sid)
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        def on_resume_selected(result: str | None) -> None:
            if not result:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            if ":" in result and (result.startswith("steal:") or result.startswith("readonly:")):
                choice, sid = result.split(":", 1)
                if choice == "steal":
                    if hasattr(app, "sm"):
                        app.sm.steal_session_lock(sid)
                    _apply_selected(sid)
                elif choice == "readonly":
                    _apply_selected(sid, read_only=True)
                return

            _apply_selected(result)

        curr_sid = getattr(app, "current_session_id", None)
        app.push_screen(ResumeScreen(sessions, current_session_id=curr_sid), callback=on_resume_selected)


class SubagentsCommand(BaseCommand):
    name = "/subagents"
    aliases = ["/agents", "/subagent"]
    description = "Manage subagents"

    async def execute(self, app) -> None:
        store = getattr(app, "sm", None)
        curr_sid = getattr(app, "current_session_id", None)

        def _has_subagents() -> bool:
            if not store:
                return False
            return bool(store.children(curr_sid) if curr_sid else store.list(kind="subagent"))

        has_sessions = await asyncio.to_thread(_has_subagents)

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
        skills = await asyncio.to_thread(get_skill_manager().list_skills)
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
        mm = get_mcp_manager()
        try:
            servers = await asyncio.to_thread(mm.load_servers)
        except Exception:
            servers = []
        if not servers:
            app.notify("No configured MCP servers found", severity="warning")
            return
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

        try:
            outcome = await compact_session(
                app.agent,
                save_session_cb=save_cb,
                on_begin=on_begin,
                on_divider_update=on_divider_update,
                refresh_footer_cb=lambda: app.refresh_status_footer(),
            )
            if outcome.success:
                try:
                    if hasattr(app, "sm") and hasattr(app, "current_session_id") and app.current_session_id:
                        sess = app.sm.get(app.current_session_id, reload=False)
                        if sess:
                            sess.add_event({"type": "event_divider", "text": outcome.title or "Session Compacted"})
                except Exception:
                    pass
            else:
                app.notify(outcome.message or "Context compaction failed", severity="warning")
        finally:
            app.is_generating = False
            if hasattr(app, "_pop_queued_for_current_session") and hasattr(app, "_process_queued_message"):
                next_item = app._pop_queued_for_current_session()
                if next_item is not None:
                    kw = {}
                    if len(next_item) > 4 and next_item[4]:
                        kw["display_text"] = next_item[4]
                    asyncio.create_task(
                        app._process_queued_message(
                            next_item[0],
                            next_item[1],
                            next_item[2],
                            **kw,
                        )
                    )
            elif getattr(app, "message_queue", None):
                next_item = app.message_queue.pop(0)
                prompt = next_item[0]
                show_in_ui = next_item[1] if len(next_item) > 1 else True
                kwargs = {"attachments": next_item[2]} if len(next_item) > 2 else {}
                if len(next_item) > 4 and next_item[4]:
                    kwargs["display_text"] = next_item[4]
                if hasattr(app, "trigger_ai_response"):
                    app.trigger_ai_response(prompt, show_in_ui=show_in_ui, **kwargs)


class QuestionsCommand(BaseCommand):
    name = "/questions"
    aliases = ["/q", "/ask"]
    description = "Resume pending user questions wizard"

    async def execute(self, app) -> None:
        from widgets.presentation.screens.ask_user import AskUserWizardScreen

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


class DiffCommand(BaseCommand):
    name = "/diff"
    aliases = ["/changes", "/status", "/patch"]
    description = "View workspace diff since session checkpoint"

    async def execute(self, app) -> None:
        from core.application.session.actions import get_session_diff
        from widgets.presentation.screens.diff import DiffScreen

        curr_sid = getattr(app, "current_session_id", None)
        proj_path = getattr(app.sm, "project_path", None) if hasattr(app, "sm") else None

        if not curr_sid:
            app.notify("No active session found", severity="warning")
            return

        diff_items = await get_session_diff(curr_sid, project_path=proj_path)
        if not diff_items:
            app.notify("No workspace changes found since session start", severity="info")
            return

        app.push_screen(DiffScreen(diff_items, title="Session Changes"))


class SandboxCommand(BaseCommand):
    name = "/sandbox"
    aliases = ["/sb"]
    description = "Toggle shell command sandbox (ON/OFF)"

    async def execute(self, app) -> None:
        if not hasattr(app, "sandbox_enabled"):
            app.sandbox_enabled = False
        app.sandbox_enabled = not app.sandbox_enabled
        msg = "Sandbox enabled" if app.sandbox_enabled else "Sandbox disabled"
        severity = "info" if app.sandbox_enabled else "warning"

        from core.infrastructure.config.config_helpers import save_sandbox_config

        try:
            save_sandbox_config(app.sandbox_enabled)
        except Exception:
            pass

        if hasattr(app, "refresh_status_footer"):
            app.refresh_status_footer()

        if hasattr(app, "notify"):
            app.notify(msg, severity=severity)


class CopyCommand(BaseCommand):
    name = "/copy"
    aliases = ["/cp", "/yank"]
    description = "Copy last assistant response to clipboard"

    async def execute(self, app) -> None:
        try:
            chat_view = app.query_one(ChatView)
            text = chat_view.get_last_bot_message_text()
            if text:
                app.copy_to_clipboard(text)
            else:
                app.notify("No assistant response to copy", severity="warning")
        except Exception:
            app.notify("Failed to copy assistant response", severity="error")



class ThemeCommand(BaseCommand):
    name = "/theme"
    aliases = ["/themes", "/color", "/colors"]
    description = "Switch color theme (Zinc, Dracula, Catppuccin, Nord...)"

    async def execute(self, app) -> None:
        from core.theme_manager import theme_manager
        from widgets.presentation.screens.theme import ThemeScreen

        def on_theme_selected(selected: str | None) -> None:
            if selected:
                theme = theme_manager.get(selected)
                if theme:
                    if hasattr(app, "set_app_theme"):
                        app.set_app_theme(theme.name)
                    else:
                        theme_manager.set_theme(theme.name)
                        if hasattr(app, "theme"):
                            app.theme = theme.name
                            if hasattr(app, "refresh_css"):
                                app.refresh_css()
                    if hasattr(app, "notify"):
                        app.notify(f"Theme switched to {theme.label}", severity="information")

        app.push_screen(ThemeScreen(), callback=on_theme_selected)

COMMAND_CLASSES = [
    ThemeCommand,
    HelpCommand,
    NewCommand,
    CopyCommand,
    ProvidersCommand,
    ModelsCommand,
    ThinkingEffortCommand,
    RewindCommand,
    ForkCommand,
    RenameCommand,
    ResumeCommand,
    SubagentsCommand,
    ShellTasksCommand,
    SkillsCommand,
    MCPCommand,
    CompactCommand,
    QuestionsCommand,
    DiffCommand,
    SandboxCommand,
]


