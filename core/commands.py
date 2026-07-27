
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
    VisionWarningScreen,
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
    description = "Help and keybindings"

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
        grouped_models = await app.pm.fetch_models_grouped()
        if not grouped_models:
            app.notify("Failed to fetch models", severity="warning")
            return

        curr_provider = app.pm.get_active_provider_key()
        curr_model = getattr(app.agent, "model", "") if getattr(app, "agent", None) else ""
        if not curr_model and hasattr(app.pm, "get_provider_model"):
            curr_model = app.pm.get_provider_model(curr_provider)

        def on_model_selected(selection: Any) -> None:
            if selection:
                is_vision_tab = False
                if isinstance(selection, tuple) and len(selection) == 2 and isinstance(selection[1], bool):
                    item_val, is_vision_tab = selection[0], selection[1]
                else:
                    item_val = selection

                if isinstance(item_val, (tuple, list)):
                    selected_prov, selected_model = item_val[0], item_val[1]
                else:
                    selected_prov = curr_provider
                    selected_model = item_val

                if is_vision_tab:
                    catalog.set_fallback_vision_model(selected_prov, selected_model)
                    app.query_one("#message-input", ChatInput).focus()
                    return

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
                clean_selected = catalog.get_model_display_name(selected_prov, selected_model)
                app.notify(f"Model switched: {clean_selected}")

                if catalog.is_native_vision(selected_prov, selected_model):
                    catalog.set_fallback_vision_model(selected_prov, selected_model)
                else:
                    def on_warning_action(action: str | None) -> None:
                        if action == "select_vision":
                            catalog.remove_vision_override(selected_model)

                            def on_fallback_vision_selected(fb_selection: Any) -> None:
                                if fb_selection:
                                    fb_val = (
                                        fb_selection[0]
                                        if isinstance(fb_selection, tuple)
                                        and len(fb_selection) == 2
                                        and isinstance(fb_selection[1], bool)
                                        else fb_selection
                                    )
                                    if isinstance(fb_val, (tuple, list)):
                                        f_prov, f_model = fb_val[0], fb_val[1]
                                    else:
                                        f_prov = selected_prov
                                        f_model = fb_val
                                    catalog.set_fallback_vision_model(f_prov, f_model)

                            app.push_screen(
                                ModelScreen(grouped_models, selected_model, selected_prov, initial_tab="vision"),
                                callback=on_fallback_vision_selected,
                            )
                        elif action == "force_vision":
                            catalog.add_vision_override(selected_model)
                            catalog.set_fallback_vision_model(selected_prov, selected_model)
                        elif action == "use_fallback":
                            catalog.remove_vision_override(selected_model)
                            fb_prov, fb_model = catalog.get_fallback_vision_model()
                            if not fb_model:
                                vision_models = getattr(catalog, "_vision", [])
                                if vision_models:
                                    catalog.set_fallback_vision_model(selected_prov, vision_models[0])
                            elif fb_prov:
                                catalog.set_fallback_vision_model(fb_prov, fb_model)

                    app.push_screen(VisionWarningScreen(selected_model, selected_prov), callback=on_warning_action)
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
            app.notify(f"Thinking effort: {effort}")
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
        if curr_sid:
            try:
                from core.git_checkpoint import GitCheckpointManager
                for seq_idx, (child_idx, text) in enumerate(user_msgs):
                    stat = GitCheckpointManager.get_diff_stats(curr_sid, seq_idx, project_path=proj_path) or ""
                    msgs_with_stats.append((child_idx, text, stat))
            except Exception:
                msgs_with_stats = [(child_idx, text, "") for child_idx, text in user_msgs]
        else:
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

                # Restore Git checkpoint state if available
                checkpoint_restored = False
                if curr_sid:
                    try:
                        from core.git_checkpoint import GitCheckpointManager
                        checkpoint_restored = GitCheckpointManager.restore_checkpoint(curr_sid, seq_idx, project_path=proj_path)
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

                if checkpoint_restored:
                    app.notify("Chat and git state rolled back! Message loaded into input field.")
                else:
                    app.notify("Chat rolled back! Message loaded into input field.")
            app.query_one("#message-input").focus()

        app.push_screen(RewindScreen(msgs_with_stats), callback=on_rewind_selected)


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


INIT_PROMPT_TEMPLATE = """Create or update `AGENTS.md` for this repository.


The goal is a compact instruction file that helps future AI sessions avoid mistakes and ramp up quickly. Every line should answer: "Would an agent likely miss this without help?" If not, leave it out.

## How to investigate
Read the highest-value sources first:
- `README*`, root manifests, workspace config, lockfiles
- build, test, lint, formatter, typecheck, and codegen config
- CI workflows and pre-commit / task runner config
- existing instruction files (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `.cursorrules`)

If architecture is still unclear after reading config and docs, inspect representative code files to find real entrypoints and boundaries.

## Writing rules
Include only high-signal, repo-specific guidance such as:
- exact commands and shortcuts the agent would otherwise guess wrong
- architecture notes that are not obvious from filenames
- conventions that differ from language or framework defaults

When in doubt, omit. Prefer short sections and bullets.
If `AGENTS.md` already exists, improve it in place rather than rewriting blindly."""

class InitCommand(BaseCommand):
    name = "/init"
    description = "Guided `AGENTS.md` project setup"

    async def execute(self, app) -> None:
        app.trigger_ai_response(INIT_PROMPT_TEMPLATE, show_in_ui=True)


HANDOFF_PROMPT_TEMPLATE = """Prepare a concise handoff note for the next AI session.

Output the handoff in chat only. Do not create, edit, or delete files unless the user explicitly asks for that in a follow-up.

Include only information that would help another agent continue correctly:
- current goal and user intent
- relevant decisions and constraints
- files, modules, or commands already inspected
- work completed so far
- remaining tasks or next steps
- verification status, including tests or checks run
- known risks, blockers, or assumptions

If there is little or no prior session context, say that explicitly.
Do not infer completed work, inspected files, decisions, or verification that are not present in the conversation.

Prefer short sections and bullets. Be specific enough that another agent can resume without rereading the whole conversation."""


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
                app.notify(msg)
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
                app.notify(msg, severity="warning")
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
    aliases = ["/plan", "/ask"]
    description = "Switch agent to Explore mode"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "explore"
            app.mode = "explore"
            app.refresh_status_footer()


class PolicyCommand(BaseCommand):
    name = "/policy"
    aliases = ["/permissions"]
    description = "Manage tool & capability security policies"

    async def execute(self, app) -> None:
        from widgets.screens.policy import PolicyScreen

        app.push_screen(PolicyScreen())


class DemoCommand(BaseCommand):
    name = "/demo"
    aliases = ["/fake"]
    description = "Load interactive fake agent session (0 tokens spent)"

    async def execute(self, app) -> None:
        for w in [w for w in app.workers if w.is_running]:
            w.cancel()
        app.is_generating = False
        app.message_queue.clear()

        from core.subagent_tracker import SubagentTracker
        tracker = SubagentTracker.get_instance()
        demo_task_id = "subagent-demo"
        demo_sess = tracker.create_session(
            demo_task_id,
            "Explore project architecture",
            "Explore codebase and summarize architecture",
            "explore",
            False,
            session_id=app.current_session_id
        )
        demo_sess.events.clear()
        demo_sess.add_event({"type": "user", "text": "Explore codebase architecture"})
        demo_sess.add_event({"type": "thinking_start", "val1": "Scanning project tree and config files..."})
        demo_sess.add_event({"type": "thinking_end", "duration": 0.42, "content": "Project uses Textual framework with modular provider architecture."})
        demo_sess.add_event({"type": "tool", "tool_type": "read", "target": "AGENTS.md", "args": {"path": "AGENTS.md"}})
        demo_sess.add_event({"type": "tool_result", "result_text": "AGENTS.md instructions loaded successfully."})
        demo_sess.add_event({"type": "bot_text", "text": "### **Результат исследования:**\n- **Проект**: Johnston AI Client (Textual TUI)\n- **Архитектура**: BaseAgent, PromptBuilder, SubagentTracker\n- **Статус**: Готов к работе."})
        demo_sess.finish("completed")

        from widgets.chat_view import ChatView
        chat_view = app.query_one(ChatView)
        await chat_view.remove_children()
        chat_view.clear_welcome()

        await chat_view.add_user_message("Запусти демонстрационную сессию и исследуй проект")

        tw = await chat_view.add_thinking_widget()
        tw.finish_thinking(0.42, "Checking workspace status, subagent tracker, and active tools without calling LLM API...")

        tool1 = await chat_view.add_tool_call(
            "subagent",
            "Explore project architecture",
            result_text="<task_result>\nИсследование архитектуры завершено успешно.\n</task_result>",
            args={"description": "Explore project architecture", "task_id": demo_task_id, "subagent_type": "explore"}
        )
        setattr(tool1, "subagent_task_id", demo_task_id)

        await chat_view.add_tool_call(
            "shell",
            "git status",
            result_text="On branch main\nYour branch is up to date with 'origin/main'.\nnothing to commit, working tree clean",
            args={"command": "git status"}
        )

        await chat_view.add_tool_call(
            "read",
            "AGENTS.md",
            result_text="# AI Agents in Johnston\nJohnston uses modular agent architecture...",
            args={"path": "AGENTS.md"}
        )

        await chat_view.add_tool_call(
            "ask_user",
            "Какой фреймворк добавить в проект?",
            result_text="Question: Какой фреймворк добавить в проект?\nAnswer: FastAPI (рекомендуется)",
            args={
                "questions": [
                    {
                        "question_text": "Какой фреймворк добавить в проект?",
                        "options": ["FastAPI (рекомендуется)", "Django", "Flask", "Aiohttp"]
                    }
                ]
            }
        )

        bot_msg = await chat_view.add_bot_message()
        bot_msg.content = (
            "### 🚀 **Демонстрационная фейковая сессия активна!** (0 токенов потрачено)\n\n"
            "Все виджеты интерактивны:\n"
            "- ❓ **AskUser**: открыто интерактивное модальное окно с выбором опций!\n"
            "- ⚙ **Subagent**: кликни по плашке `subagent` выше, чтобы открыть модалку логов просмотра!\n"
            "- ⚙ **Shell / Read / AskUser**: кликни по плашкам, чтобы развернуть вызовы инструментов.\n"
            "- 💡 `/subagents`: открывает список субагентов.\n"
            "- 💡 `/tasks`: открывает фоновые задачи."
        )

        app.refresh_status_footer()
        app.notify("Фейковая демо-сессия загружена (0 токенов потрачено)")

        try:
            from widgets.modal_screens import QuestionScreen
            screen = QuestionScreen(
                num_text="### **Demo Question 1/1**",
                question_text="Какой фреймворк или библиотеку добавить в проект?",
                options=["FastAPI (рекомендуется)", "Django", "Flask", "Aiohttp"],
                current_val="FastAPI (рекомендуется)"
            )
            def on_demo_q_dismiss(res):
                if res and isinstance(res, dict) and res.get("answer"):
                    app.notify(f"Демо ask_user ответ: {res['answer']}")
            app.push_screen(screen, callback=on_demo_q_dismiss)
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
    PolicyCommand,
    InitCommand,
    HandoffCommand,
    CompactCommand,
    ActionCommand,
    ExploreCommand,
    DemoCommand,
]


COMMAND_REGISTRY = {}
for cls in COMMAND_CLASSES:
    COMMAND_REGISTRY[cls.name] = cls
    for alias in getattr(cls, "aliases", []):
        COMMAND_REGISTRY[alias] = cls

async def handle_slash_command(app, command_text: str) -> bool:
    """Executes command if registered. Returns True if handled."""
    parts = command_text.strip().split(maxsplit=1)
    cmd_name = parts[0].lower()

    # Normalization of Cyrillic homoglyphs to Latin (to handle layout errors)
    homoglyphs = {
        'а': 'a', 'в': 'b', 'е': 'e', 'к': 'k', 'м': 'm', 'н': 'h',
        'о': 'o', 'р': 'p', 'с': 'c', 'т': 't', 'у': 'y', 'х': 'x'
    }
    normalized_name = "".join(homoglyphs.get(c, c) for c in cmd_name)
    parts[0] = normalized_name

    if normalized_name in COMMAND_REGISTRY:
        cmd_instance = COMMAND_REGISTRY[normalized_name]()
        await cmd_instance.execute(app)
        return True

    # Skill slash command execution (e.g. /caveman [optional text])
    if normalized_name.startswith("/"):
        skill_name = normalized_name[1:]
        sm = SkillManager()
        skill = sm.get_skill(skill_name)
        if skill:
            extra_text = parts[1].strip() if len(parts) > 1 else ""
            if extra_text:
                prompt = f"Load and apply the skill '{skill['name']}'.\n\nUser request: {extra_text}"
            else:
                prompt = f"Load and apply the skill '{skill['name']}'."
            app.trigger_ai_response(prompt, show_in_ui=True)
            return True

    return False
