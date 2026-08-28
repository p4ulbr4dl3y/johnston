"""UI and system slash commands (help, copy, theme)."""
from __future__ import annotations

from widgets.chat_input import ChatInput
from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.screens.constants import MESSAGE_INPUT
from widgets.presentation.screens.help import HelpScreen
from widgets.presentation.widgets.chat_container import ChatView


class HelpCommand(BaseCommand):
    name = "/help"
    aliases = ["/h", "/?"]
    description = "Show help and keybindings"

    async def execute(self, app) -> None:
        app.push_screen(HelpScreen())


class CopyCommand(BaseCommand):
    name = "/copy"
    aliases = ["/cp", "/yank"]
    description = "Copy last assistant response"

    async def execute(self, app) -> None:
        try:
            chat_view = app.query_one(ChatView)
            text = chat_view.get_last_bot_message_text()
            if text:
                app.copy_to_clipboard(text)
                if hasattr(app, "notify"):
                    app.notify("Copied to clipboard", severity="information", timeout=1.5)
            else:
                if hasattr(app, "notify"):
                    app.notify("No assistant response to copy", severity="warning")
        except Exception:
            if hasattr(app, "notify"):
                app.notify("Failed to copy assistant response", severity="error")


class ThemeCommand(BaseCommand):
    name = "/theme"
    aliases = ["/themes", "/color", "/colors"]
    description = "Switch UI color theme"

    async def execute(self, app) -> None:
        from widgets.app.theme_manager import theme_manager
        from widgets.presentation.screens.theme import ThemeScreen

        def on_theme_selected(selected: str | None) -> None:
            if not selected:
                if hasattr(app, "query_one"):
                    try:
                        app.query_one(MESSAGE_INPUT, ChatInput).focus()
                    except Exception:
                        pass
                return

            theme = theme_manager.get(selected)
            if theme:
                if hasattr(app, "set_app_theme"):
                    app.set_app_theme(theme.name, persist=True)
                else:
                    theme_manager.set_theme(theme.name)
                    if hasattr(app, "theme"):
                        app.theme = theme.name
                        if hasattr(app, "refresh_css"):
                            app.refresh_css()

            if hasattr(app, "query_one"):
                try:
                    app.query_one(MESSAGE_INPUT, ChatInput).focus()
                except Exception:
                    pass

        app.push_screen(ThemeScreen(theme_manager.current_theme.name), callback=on_theme_selected)
