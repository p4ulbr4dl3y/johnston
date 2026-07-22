from typing import Dict, Type

from core.skill_manager import SkillManager
from widgets.chat_input import ChatInput
from widgets.chat_view import BotMessage, ChatView
from widgets.modal_screens import (
    ApiKeyInputScreen,
    ConnectProviderScreen,
    HelpScreen,
    MCPScreen,
    ModelScreen,
    ResumeScreen,
    RewindScreen,
    SkillsScreen,
    TasksListScreen,
)


class BaseCommand:
    """Базовый класс для слэш-команд"""
    name: str = ""
    description: str = ""

    async def execute(self, app) -> None:
        raise NotImplementedError


class HelpCommand(BaseCommand):
    name = "/help"
    description = "Help and keybindings"

    async def execute(self, app) -> None:
        app.push_screen(HelpScreen())


class NewCommand(BaseCommand):
    name = "/new"
    description = "Start a new chat session"

    async def execute(self, app) -> None:
        for w in [w for w in app.workers if w.is_running]:
            w.cancel()
        app.current_session_id = app.sm.generate_session_id()
        chat_view = app.query_one(ChatView)
        await chat_view.remove_children()
        chat_view.check_welcome()
        if hasattr(app.agent, "clear_history"):
            app.agent.clear_history()
        elif hasattr(app.agent, "history"):
            app.agent.history = []
        app.refresh_status_footer()
        app.notify("New chat session created!")


class ConnectCommand(BaseCommand):
    name = "/connect"
    description = "Connect AI provider and configure API key"

    async def execute(self, app) -> None:
        providers = app.pm.load_providers()
        if not providers:
            app.notify("No available providers in project providers/", severity="warning")
            return

        active_key = app.pm.get_active_provider_key()
        configured_keys = {
            k: app.pm.get_api_key(k) for k in providers
        }

        def on_provider_selected(selected_key: str | None) -> None:
            if not selected_key:
                app.query_one("#message-input", ChatInput).focus()
                return

            provider_info = providers.get(selected_key, {})
            p_name = provider_info.get("name", selected_key)
            curr_key = app.pm.get_api_key(selected_key)

            def on_key_entered(entered_key: str | None) -> None:
                if entered_key is not None:
                    if entered_key:
                        app.pm.set_provider_api_key(selected_key, entered_key)
                    app.pm.set_active_provider_key(selected_key)
                    app.agent = app.pm.create_active_agent()
                    app.agent.app = app
                    app.refresh_status_footer()
                    app.notify(f"Connected to provider: {p_name}")
                app.query_one("#message-input", ChatInput).focus()

            app.push_screen(ApiKeyInputScreen(p_name, selected_key, curr_key), callback=on_key_entered)

        app.push_screen(ConnectProviderScreen(providers, active_key, configured_keys), callback=on_provider_selected)


class ProviderCommand(ConnectCommand):
    """Алиас команды /provider на /connect"""
    name = "/provider"
    description = "Connect AI provider (alias for /connect)"


class ModelsCommand(BaseCommand):
    name = "/models"
    description = "Switch model for providers"

    async def execute(self, app) -> None:
        grouped_models = await app.pm.fetch_models_grouped()
        if not grouped_models:
            app.notify("Failed to fetch models", severity="warning")
            return

        curr_provider = app.pm.get_active_provider_key()
        curr_model = getattr(app.agent, "model", "")

        def on_model_selected(selection: tuple[str, str] | str | None) -> None:
            if selection:
                if isinstance(selection, (tuple, list)):
                    selected_prov, selected_model = selection[0], selection[1]
                else:
                    selected_prov = curr_provider
                    selected_model = selection

                if selected_prov != app.pm.get_active_provider_key():
                    app.pm.set_active_provider_key(selected_prov)
                    app.agent = app.pm.create_active_agent()
                    app.agent.app = app

                if hasattr(app.agent, "model"):
                    app.agent.model = selected_model
                app.pm.set_provider_model(selected_prov, selected_model)
                app.refresh_status_footer()
                app.notify(f"Model switched: [{selected_prov}] {selected_model}")
            app.query_one("#message-input", ChatInput).focus()

        app.push_screen(ModelScreen(grouped_models, curr_model, curr_provider), callback=on_model_selected)


class RewindCommand(BaseCommand):
    name = "/rewind"
    description = "Rollback chat history to a message"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        user_msgs = chat_view.get_user_messages()
        if not user_msgs:
            app.notify("History is empty: no messages to rollback", severity="warning")
            return

        def on_rewind_selected(selected_idx: int | None) -> None:
            if selected_idx is not None and selected_idx >= 0:
                # Находим исходный текст сообщения, до которого откатываемся
                msg_text = ""
                for idx, text in user_msgs:
                    if idx == selected_idx:
                        msg_text = text
                        break

                # Откатываем чат до позиции непосредственно перед выбранным сообщением
                chat_view.rollback_to(selected_idx - 1)

                if hasattr(app.agent, "clear_history"):
                    app.agent.clear_history()
                elif hasattr(app.agent, "history"):
                    app.agent.history = []

                app.save_current_session()

                # Загружаем текст в поле ввода
                chat_input = app.query_one("#message-input")
                chat_input.load_text(msg_text)
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))

                app.notify("Chat rolled back! Message loaded into input field.")
            app.query_one("#message-input").focus()

        app.push_screen(RewindScreen(user_msgs), callback=on_rewind_selected)


class ResumeCommand(BaseCommand):
    name = "/resume"
    description = "Resume a saved session"

    async def execute(self, app) -> None:
        sessions = app.sm.list_sessions()
        if not sessions:
            app.notify("No saved sessions in this project", severity="warning")
            return

        def on_resume_selected(selected_sid: str) -> None:
            if selected_sid:
                app.load_session_ui(selected_sid)
                app.notify(f"Session resumed: {selected_sid}")
            app.query_one("#message-input", ChatInput).focus()

        app.push_screen(ResumeScreen(sessions), callback=on_resume_selected)


class TasksCommand(BaseCommand):
    name = "/tasks"
    description = "Manage background tasks"

    async def execute(self, app) -> None:
        if not app.background_tasks:
            app.notify("No active background tasks", severity="warning")
            return
        app.push_screen(TasksListScreen())


class SkillsCommand(BaseCommand):
    name = "/skills"
    description = "Browse and activate available skills"

    async def execute(self, app) -> None:
        sm = SkillManager()
        skills = sm.list_skills()
        if not skills:
            app.notify("No available skills found (~/.johnston/skills/ or .johnston/skills/)", severity="warning")
            return

        def on_skill_selected(selected_skill: dict | None) -> None:
            if selected_skill:
                s_name = selected_skill["name"]
                app.notify(f"Activating skill: {s_name}")
                app.generate_ai_response(f"Load and apply the skill '{s_name}'.", show_in_ui=True)
            app.query_one("#message-input", ChatInput).focus()

        app.push_screen(SkillsScreen(), callback=on_skill_selected)


class MCPCommand(BaseCommand):
    name = "/mcp"
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
    description = "Guided AGENTS.md project setup"

    async def execute(self, app) -> None:
        app.notify("Initializing AGENTS.md guide for this project...")
        app.generate_ai_response(INIT_PROMPT_TEMPLATE, show_in_ui=True)


class CompactCommand(BaseCommand):
    name = "/compact"
    description = "Compact session conversation history with AI summary"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent found", severity="error")
            return

        app.notify("Compacting conversation context...")
        if hasattr(app.agent, "compact_history"):
            success, msg = await app.agent.compact_history()
            if success:
                app.notify(msg)
                if hasattr(app, "refresh_status_footer"):
                    app.refresh_status_footer()
            else:
                app.notify(msg, severity="warning")
        else:
            app.notify("Active agent does not support context compaction", severity="warning")


class PlanCommand(BaseCommand):
    name = "/plan"
    description = "Switch agent to Plan mode"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "plan"
            if hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()
        else:
            app.notify("No active agent", severity="error")


class BuildCommand(BaseCommand):
    name = "/build"
    description = "Switch agent to Build mode"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "build"
            if hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()
        else:
            app.notify("No active agent", severity="error")


class ModeCommand(BaseCommand):
    name = "/mode"
    description = "Toggle agent mode (PLAN / BUILD)"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent", severity="error")
            return

        curr = getattr(app.agent, "mode", "build")
        new_mode = "build" if curr == "plan" else "plan"
        app.agent.mode = new_mode
        if hasattr(app, "refresh_status_footer"):
            app.refresh_status_footer()


class PasteCommand(BaseCommand):
    name = "/paste"
    description = "Universal paste from clipboard (text or image)"

    async def execute(self, app) -> None:
        chat_input = app.query_one("#message-input", ChatInput)
        if not chat_input.paste_universal_clipboard():
            app.notify("Clipboard is empty", severity="warning")
        chat_input.focus()


class CopyCommand(BaseCommand):
    name = "/copy"
    description = "Copy last assistant message to clipboard"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        last_bot_text = ""

        for child in reversed(chat_view.children):
            if isinstance(child, BotMessage) and child.content:
                last_bot_text = child.content
                break

        if last_bot_text:
            try:
                app.copy_to_clipboard(last_bot_text)
            except Exception:
                pass

            import subprocess
            try:
                subprocess.run(["pbcopy"], input=last_bot_text.encode("utf-8"), check=True)
            except Exception:
                pass

            app.notify("Copied last assistant message!")
        else:
            app.notify("No assistant message to copy", severity="warning")

        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()


COMMAND_REGISTRY: Dict[str, Type[BaseCommand]] = {
    cmd.name: cmd for cmd in [
        HelpCommand,
        NewCommand,
        ConnectCommand,
        ProviderCommand,
        ModelsCommand,
        RewindCommand,
        ResumeCommand,
        TasksCommand,
        SkillsCommand,
        MCPCommand,
        InitCommand,
        CompactCommand,
        PlanCommand,
        BuildCommand,
        ModeCommand,
        PasteCommand,
        CopyCommand,
    ]
}

async def handle_slash_command(app, command_text: str) -> bool:
    """Выполняет команду, если она зарегистрирована. Возвращает True, если обработана."""
    parts = command_text.strip().split(maxsplit=1)
    cmd_name = parts[0].lower()

    # Нормализация кириллических омоглифов в латиницу (для исключения ошибок раскладки)
    homoglyphs = {
        'а': 'a', 'в': 'b', 'е': 'e', 'к': 'k', 'м': 'm', 'н': 'h',
        'о': 'o', 'р': 'p', 'с': 'c', 'т': 't', 'у': 'y', 'х': 'x'
    }
    normalized_name = "".join(homoglyphs.get(c, c) for c in cmd_name)

    if normalized_name in COMMAND_REGISTRY:
        cmd_instance = COMMAND_REGISTRY[normalized_name]()
        await cmd_instance.execute(app)
        return True
    return False
