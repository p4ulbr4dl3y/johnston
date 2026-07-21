from typing import Dict, Type

from core.skill_manager import SkillManager
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.modal_screens import (
    HelpScreen,
    MCPScreen,
    ModelScreen,
    ProviderScreen,
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


class ProviderCommand(BaseCommand):
    name = "/provider"
    description = "Switch AI provider"

    async def execute(self, app) -> None:
        providers = app.pm.load_providers()
        if not providers:
            app.notify("No available providers", severity="warning")
            return

        def on_provider_selected(selected_key: str) -> None:
            if selected_key:
                app.pm.set_active_provider_key(selected_key)
                app.agent = app.pm.create_active_agent()
                app.agent.app = app
                app.refresh_status_footer()
                app.notify(f"Provider switched: {selected_key}")
            app.query_one("#message-input", ChatInput).focus()

        app.push_screen(ProviderScreen(providers), callback=on_provider_selected)


class ModelsCommand(BaseCommand):
    name = "/models"
    description = "Switch model for active provider"

    async def execute(self, app) -> None:
        active_key = app.pm.get_active_provider_key()
        app.notify(f"Loading models for {active_key}...")
        models = await app.pm.fetch_models_for_provider(active_key)
        if not models:
            app.notify("Failed to fetch models", severity="warning")
            return

        curr_model = getattr(app.agent, "model", "")

        def on_model_selected(selected_model: str) -> None:
            if selected_model:
                if hasattr(app.agent, "model"):
                    app.agent.model = selected_model
                app.pm.set_provider_model(active_key, selected_model)
                app.refresh_status_footer()
                app.notify(f"Model switched: {selected_model}")
            app.query_one("#message-input", ChatInput).focus()

        app.push_screen(ModelScreen(models, curr_model), callback=on_model_selected)


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
            app.notify("Mode switched: PLAN")
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
            app.notify("Mode switched: BUILD")
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
        app.notify(f"Mode switched: {new_mode.upper()}")


COMMAND_REGISTRY: Dict[str, Type[BaseCommand]] = {
    cmd.name: cmd for cmd in [
        HelpCommand,
        NewCommand,
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
