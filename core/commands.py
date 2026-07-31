
import asyncio
from typing import Any

from core.models_catalog import catalog
from core.skill_manager import SkillManager
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.modal_screens import (
    HelpScreen,
    MCPScreen,
    ModelScreen,
    ResumeScreen,
    RewindScreen,
    SkillsScreen,
    TasksListScreen,
    ThinkingEffortScreen,
)


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
        for w in [w for w in app.workers if w.is_running]:
            w.cancel()
        # Reset generation state synchronously: cancelled workers clear is_generating
        # in their own finally, but that runs asynchronously, so /new could leave the
        # app stuck "generating" and swallow subsequent input into the queue.
        app.is_generating = False
        app.message_queue.clear()
        app.current_session_id = app.sm.generate_session_id()
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
                    app.query_one("#message-input", ChatInput).focus()
                    return

                p_info = provs.get(selected_key, {})
                p_name = p_info.get("name", selected_key)
                curr_key = app.pm.get_api_key(selected_key)

                def on_key_entered(entered_key: str | None) -> None:
                    if entered_key is not None:
                        if entered_key:
                            app.pm.set_provider_api_key(selected_key, entered_key)
                            app.pm.set_provider_disabled(selected_key, False)
                        old_history = list(getattr(app.agent, "history", [])) if getattr(app, "agent", None) else []
                        current_mode = getattr(app, "mode", getattr(app.agent, "mode", "action"))
                        app.pm.set_active_provider_key(selected_key)
                        app.agent = app.pm.create_active_agent()
                        if app.agent and old_history:
                            app.agent.history = old_history
                        if app.agent:
                            app.agent.mode = current_mode
                            app.agent.app = app
                        app.mode = current_mode
                        app.refresh_status_footer()
                        app.notify(f"Connected to provider: {p_name}")
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
            app.notify("Could not fetch models for connected provider. Please check API key or network connection.", severity="warning")
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
                    old_history = list(getattr(app.agent, "history", [])) if getattr(app, "agent", None) else []
                    current_mode = getattr(app, "mode", getattr(app.agent, "mode", "action"))
                    app.pm.set_active_provider_key(selected_prov)
                    app.agent = app.pm.create_active_agent()
                    if app.agent and old_history:
                        app.agent.history = old_history
                    if app.agent:
                        app.agent.mode = current_mode
                        app.agent.app = app
                    app.mode = current_mode

                if hasattr(app.agent, "model"):
                    app.agent.model = selected_model
                app.pm.set_provider_model(selected_prov, selected_model)
                app.refresh_status_footer()
            app.query_one("#message-input", ChatInput).focus()

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
                app.query_one("#message-input", ChatInput).focus()
                return

            current_mode = getattr(app, "mode", getattr(getattr(app, "agent", None), "mode", "action"))
            old_history = getattr(getattr(app, "agent", None), "history", [])
            if hasattr(app.pm, "set_provider_thinking_effort"):
                app.pm.set_provider_thinking_effort(provider_key, model_name, effort)
            app.agent = app.pm.create_active_agent()
            app.agent.history = old_history
            app.agent.mode = current_mode
            app.agent.app = app
            app.mode = current_mode
            app.refresh_status_footer()
            app.query_one("#message-input", ChatInput).focus()

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
            checkpoints_enabled = GitCheckpointManager.is_valid_checkpoint_target(proj_path)
            if curr_sid and checkpoints_enabled:
                for seq_idx, (child_idx, text) in enumerate(user_msgs):
                    stat = GitCheckpointManager.get_diff_stats(curr_sid, seq_idx, project_path=proj_path) or ""
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
                    try:
                        from core.git_checkpoint import GitCheckpointManager
                        GitCheckpointManager.restore_checkpoint(curr_sid, seq_idx, project_path=proj_path)
                        GitCheckpointManager.purge_checkpoints_after(curr_sid, seq_idx, project_path=proj_path)
                    except Exception as e:
                        print(f"Git checkpoint restore failed: {e}")

                app.refresh_status_footer()
                app.save_current_session()

                # Load text into input field
                chat_input = app.query_one("#message-input")
                chat_input.load_text(msg_text)
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            app.query_one("#message-input").focus()

        app.push_screen(RewindScreen(msgs_with_stats, checkpoints_enabled=checkpoints_enabled), callback=on_rewind_selected)


class ResumeCommand(BaseCommand):
    name = "/resume"
    aliases = ["/sessions", "/load"]
    description = "Resume a saved session"

    async def execute(self, app) -> None:
        sessions = app.sm.list_sessions()
        if not sessions:
            app.notify("No saved sessions in this project", severity="warning")
            return

        def on_resume_selected(selected_sid: str) -> None:
            if selected_sid:
                app.load_session_ui(selected_sid)
            app.query_one("#message-input", ChatInput).focus()

        app.push_screen(ResumeScreen(sessions), callback=on_resume_selected)


class TasksCommand(BaseCommand):
    name = "/tasks"
    aliases = ["/task"]
    description = "Manage background tasks"

    async def execute(self, app) -> None:
        if not app.background_tasks:
            app.notify("No active background tasks", severity="warning")
            return
        app.push_screen(TasksListScreen())


class SubagentsCommand(BaseCommand):
    name = "/subagents"
    aliases = ["/agents", "/subagent"]
    description = "Browse and manage subagents"

    async def execute(self, app) -> None:
        from core.subagent_tracker import SubagentTracker
        from widgets.screens.subagents import SubagentsScreen

        curr_session_id = getattr(app, "current_session_id", None)
        sessions = SubagentTracker.get_instance().get_sessions_for_session(curr_session_id)
        if not sessions:
            app.notify("No subagents registered for this session", severity="warning")
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
            app.notify("No available skills found (~/.johnston/skills/ or .johnston/skills/)", severity="warning")
            return

        def on_skill_selected(selected_skill: dict | None) -> None:
            chat_input = app.query_one("#message-input", ChatInput)
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


INIT_PROMPT_TEMPLATE = """## Task: Repository Initialization

### Goal
Create or update `AGENTS.md` for this repository to help future AI sessions avoid mistakes and ramp up quickly.

### Investigation Protocol
Read high-value sources first:
1. `README*`, root manifests, workspace config, lockfiles
2. Build, test, lint, formatter, typecheck, and codegen config
3. CI workflows and pre-commit / task runner config
4. Existing instruction files (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `.cursorrules`)

If architecture is still unclear, inspect representative code files to find entrypoints and boundaries.

### Writing Rules
Include high-signal, repo-specific guidance:
1. Exact commands and shortcuts the agent would otherwise guess wrong
2. Architecture notes not obvious from filenames
3. Conventions that differ from language or framework defaults

When in doubt, omit. Prefer short sections and bullets.
If `AGENTS.md` already exists, improve it in place rather than rewriting blindly."""

class InitCommand(BaseCommand):
    name = "/init"
    description = "Start guided `AGENTS.md` setup"

    async def execute(self, app) -> None:
        app.trigger_ai_response(INIT_PROMPT_TEMPLATE, show_in_ui=True)


HANDOFF_PROMPT_TEMPLATE = """## Task: Session Continuation Note

### Goal
Create or update `HANDOFF.md` for this repository to enable another agent to continue work seamlessly.

### Execution Constraints
1. Do not output the handoff note in chat. Write or overwrite `HANDOFF.md` in the working directory using file tools.
2. Output only a brief 1-2 sentence confirmation linking to `HANDOFF.md` in chat.

### Core Rules
Include information required to continue correctly:
1. Current goal and user intent
2. Relevant decisions and constraints
3. Files, modules, or commands already inspected
4. Work completed so far
5. Remaining tasks or next steps
6. Verification status, including tests or checks run
7. Known risks, blockers, or assumptions

### Writing Rules
1. If there is little or no prior session context, state that explicitly in the file.
2. Do not infer completed work, inspected files, decisions, or verification not present in the conversation.
3. Prefer short sections and bullets. Be specific enough that another agent can resume without rereading the whole conversation."""


class HandoffCommand(BaseCommand):
    name = "/handoff"
    description = "Prepare a continuation note for the next AI session"

    async def execute(self, app) -> None:
        app.trigger_ai_response(HANDOFF_PROMPT_TEMPLATE, show_in_ui=True)


class CompactCommand(BaseCommand):
    name = "/compact"
    aliases = ["/compress"]
    description = "Compact session conversation history with AI summary"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent found", severity="error")
            return

        if hasattr(app.agent, "compact_history"):
            success, msg = await app.agent.compact_history()
            if success:
                if hasattr(app, "refresh_status_footer"):
                    app.refresh_status_footer()
                if hasattr(app, "query_one"):
                    try:
                        from widgets.chat_view import ChatView
                        chat_view = app.query_one(ChatView)
                        await chat_view.add_compaction_divider("Session Compacted")
                    except Exception:
                        pass
                if hasattr(app, "save_current_session"):
                    app.save_current_session()
        else:
            app.notify("Active agent does not support context compaction", severity="warning")


class ActionCommand(BaseCommand):
    name = "/action"
    aliases = ["/build", "/code"]
    description = "Switch agent to Action mode"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "action"
            app.mode = "action"
            app.refresh_status_footer()


class ExploreCommand(BaseCommand):
    name = "/explore"
    description = "Switch agent to Explore mode"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "explore"
            app.mode = "explore"
            app.refresh_status_footer()


class ExpandCommand(BaseCommand):
    name = "/expand"
    aliases = ["/exp"]
    description = "Expand or collapse tool call and thinking widgets (all, collapse, or last)"

    async def execute(self, app, args: list[str] | None = None) -> None:
        try:
            chat_view = app.query_one(ChatView)
            submode = args[0].lower() if args and len(args) > 0 else "all"
            chat_view.toggle_expand(submode)
        except Exception:
            pass


class DetachCommand(BaseCommand):
    name = "/detach"
    aliases = ["/unattach", "/rmatt"]
    description = "Detach all attached clipboard images"

    async def execute(self, app) -> None:
        try:
            chat_input = app.query_one("#message-input", ChatInput)
            chat_input.clear_clipboard_attachments()
        except Exception:
            pass


COMMAND_CLASSES = [
    HelpCommand,
    NewCommand,
    ProvidersCommand,
    ModelsCommand,
    ThinkingEffortCommand,
    RewindCommand,
    ResumeCommand,
    TasksCommand,
    SubagentsCommand,
    SkillsCommand,
    MCPCommand,
    InitCommand,
    HandoffCommand,
    CompactCommand,
    ActionCommand,
    ExploreCommand,
    ExpandCommand,
    DetachCommand,
]




COMMAND_REGISTRY = {}
for cls in COMMAND_CLASSES:
    COMMAND_REGISTRY[cls.name] = cls
    for alias in getattr(cls, "aliases", []):
        COMMAND_REGISTRY[alias] = cls

async def handle_slash_command(app, command_text: str) -> bool:
    """Executes command if registered or skill found. Returns True if handled."""
    words = command_text.strip().split()
    if not words:
        return False

    cmd_name = words[0].lower()

    # Normalization of Cyrillic homoglyphs to Latin (to handle layout errors)
    homoglyphs = {
        'а': 'a', 'в': 'b', 'е': 'e', 'к': 'k', 'м': 'm', 'н': 'h',
        'о': 'o', 'р': 'p', 'с': 'c', 'т': 't', 'у': 'y', 'х': 'x'
    }
    normalized_name = "".join(homoglyphs.get(c, c) for c in cmd_name)

    if command_text.strip().startswith("/") and normalized_name in COMMAND_REGISTRY:
        cmd_instance = COMMAND_REGISTRY[normalized_name]()
        try:
            await cmd_instance.execute(app, args=words[1:])
        except TypeError:
            await cmd_instance.execute(app)
        return True


    # Multi-skill & single-skill slash command execution (e.g. /johnston-architect /caveman request)
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
        if len(loaded_skills) == 1:
            s = loaded_skills[0]
            skill_str = f"skill '{s['name']}' from '{s['location']}'"
        else:
            skill_str = "skills: " + ", ".join(f"'{s['name']}' from '{s['location']}'" for s in loaded_skills)
        user_request = " ".join(other_words).strip()
        if user_request:
            prompt = f"Read and follow instructions for {skill_str}.\n\nUser request: {user_request}"
        else:
            prompt = f"Read and follow instructions for {skill_str}."

        try:
            from widgets.chat_view import ChatView
            chat_view = app.query_one(ChatView)
            import asyncio
            asyncio.create_task(chat_view.add_user_message(command_text))
            app.trigger_ai_response(prompt, show_in_ui=False)
        except Exception:
            app.trigger_ai_response(prompt, show_in_ui=True)
        return True

    return False
