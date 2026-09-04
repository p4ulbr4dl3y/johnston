"""UI and system slash commands (help, copy, theme)."""
from __future__ import annotations

import asyncio

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


class CommandsCommand(BaseCommand):
    name = "/commands"
    aliases = ["/cmds"]
    description = "List all slash commands"

    async def execute(self, app) -> None:
        app.push_screen(HelpScreen(active_tab=0))


class KeybindsCommand(BaseCommand):
    name = "/keybinds"
    aliases = ["/keys", "/keybindings", "/shortcuts"]
    description = "List all hotkeys & keybindings"

    async def execute(self, app) -> None:
        app.push_screen(HelpScreen(active_tab=1))


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


class DemoCommand(BaseCommand):
    name = "/demo"
    aliases = []
    description = "Demo tool streaming lifecycle (generating -> running -> done)"

    async def execute(self, app) -> None:
        try:
            chat_view = app.query_one(ChatView)
        except Exception:
            return

        async def run_demo():
            # 1. create
            w1 = await chat_view.add_tool_call("create", "", status="generating")
            await asyncio.sleep(1.5)
            w1.update_tool_call(target="src/config.py", args={"path": "src/config.py"})
            await asyncio.sleep(2.0)
            w1.mark_running()
            await asyncio.sleep(1.5)
            w1.set_result("DEBUG = True\nPORT = 8080\n", status="done")
            await asyncio.sleep(1.2)

            # 2. edit
            w2 = await chat_view.add_tool_call("edit", "", status="generating")
            await asyncio.sleep(1.5)
            w2.update_tool_call(target="src/config.py", args={"path": "src/config.py"})
            await asyncio.sleep(2.0)
            w2.mark_running()
            await asyncio.sleep(1.5)
            sample_diff = (
                "--- a/src/config.py\n"
                "+++ b/src/config.py\n"
                "@@ -1,2 +1,3 @@\n"
                " DEBUG = True\n"
                "+HOST = '0.0.0.0'\n"
                " PORT = 8080\n"
            )
            w2.set_result(sample_diff, status="done")
            await asyncio.sleep(1.2)

            # 3. invoke_subagent
            w3 = await chat_view.add_tool_call("invoke_subagent", "", status="generating")
            await asyncio.sleep(1.5)
            w3.update_tool_call(target="Code Reviewer", args={"title": "Code Reviewer"})
            await asyncio.sleep(2.0)
            w3.mark_running()
            await asyncio.sleep(1.5)
            w3.set_result("Subagent finished analysis: no issues found.", status="done")
            await asyncio.sleep(1.2)

            # 4. update_plan
            w4 = await chat_view.add_tool_call("update_plan", "", status="generating")
            await asyncio.sleep(1.5)
            plan_args = {
                "plan": [
                    {"title": "Setup config", "status": "completed"},
                    {"title": "Verify tests", "status": "in_progress"},
                ]
            }
            w4.update_tool_call(target="Release Plan", args=plan_args)
            await asyncio.sleep(2.0)
            w4.mark_running()
            await asyncio.sleep(1.5)
            w4.set_result("Plan updated.", status="done")
            await asyncio.sleep(1.2)

            # 5. shell
            w5 = await chat_view.add_tool_call("shell", "", status="generating")
            await asyncio.sleep(1.5)
            w5.update_tool_call(target="pytest -v", args={"command": "pytest -v"})
            await asyncio.sleep(2.0)
            w5.mark_running()
            await asyncio.sleep(1.5)
            w5.set_result("================ 5 passed in 0.42s ================", status="done")

        task = asyncio.create_task(run_demo())
        setattr(app, "_demo_task", task)
        task.add_done_callback(lambda _: setattr(app, "_demo_task", None))
