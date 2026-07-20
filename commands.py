from typing import Dict, Type
from widgets.modal_screens import HelpScreen, RewindScreen, ResumeScreen, ProviderScreen, ModelScreen
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView

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
                chat_view.rollback_to(selected_idx)
                if hasattr(app.agent, "clear_history"):
                    app.agent.clear_history()
                elif hasattr(app.agent, "history"):
                    app.agent.history = []
                app.save_current_session()
                app.notify("History successfully rolled back!")
            app.query_one("#message-input", ChatInput).focus()

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


COMMAND_REGISTRY: Dict[str, Type[BaseCommand]] = {
    cmd.name: cmd for cmd in [
        HelpCommand,
        NewCommand,
        ProviderCommand,
        ModelsCommand,
        RewindCommand,
        ResumeCommand
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
