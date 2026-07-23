
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
    """Base class for slash commands"""
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
        app.agent.clear_history()
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
    """Alias for /connect command"""
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
                # Find original text of message being rolled back to
                msg_text = ""
                for idx, text in user_msgs:
                    if idx == selected_idx:
                        msg_text = text
                        break

                # Rollback chat to position immediately preceding selected message
                chat_view.rollback_to(selected_idx - 1)

                if hasattr(app.agent, "clear_history"):
                    app.agent.clear_history()
                elif hasattr(app.agent, "history"):
                    app.agent.history = []

                app.save_current_session()

                # Load text into input field
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
    description = "Switch agent to Action mode (execution, file edits, bash)"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "action"
            if hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()
        else:
            app.notify("No active agent", severity="error")


class ExploreCommand(BaseCommand):
    name = "/explore"
    description = "Switch agent to Explore mode (read-only research, planning, QA)"

    async def execute(self, app) -> None:
        if hasattr(app, "agent") and app.agent:
            app.agent.mode = "explore"
            if hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()
        else:
            app.notify("No active agent", severity="error")


class BuildCommand(ActionCommand):
    """Alias for /action command"""
    name = "/build"
    description = "Switch agent to Action mode"


class CodeCommand(ActionCommand):
    """Alias for /action command"""
    name = "/code"
    description = "Switch agent to Action mode"


class PlanCommand(ExploreCommand):
    """Alias for /explore command"""
    name = "/plan"
    description = "Switch agent to Explore mode"


class AskCommand(ExploreCommand):
    """Alias for /explore command"""
    name = "/ask"
    description = "Switch agent to Explore mode"


class DebugCommand(ActionCommand):
    """Alias for /action command"""
    name = "/debug"
    description = "Switch agent to Action mode"


class OrchestratorCommand(ActionCommand):
    """Alias for /action command"""
    name = "/orchestrator"
    description = "Switch agent to Action mode"


class ModeCommand(BaseCommand):
    name = "/mode"
    description = "Cycle agent mode (ACTION / EXPLORE)"

    async def execute(self, app) -> None:
        if not hasattr(app, "agent") or not app.agent:
            app.notify("No active agent", severity="error")
            return

        modes_cycle = ["action", "explore"]
        curr = getattr(app.agent, "mode", "action").lower()
        if curr in modes_cycle:
            next_idx = (modes_cycle.index(curr) + 1) % len(modes_cycle)
            new_mode = modes_cycle[next_idx]
        else:
            new_mode = "action"

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
            if isinstance(child, BotMessage):
                last_bot_text = child.full_text
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


class TestModalCommand(BaseCommand):
    name = "/testmodal"
    description = "Spawn bash confirm modal for UI testing"

    async def execute(self, app) -> None:
        from widgets.screens.bash_confirm import BashConfirmScreen
        app.push_screen(BashConfirmScreen("cd /Users/yegor/testing && echo -e \"John\\ny\" | python3 script.py", "Test command"))


class SubagentsCommand(BaseCommand):
    name = "/subagents"
    description = "View and manage subagents"

    async def execute(self, app) -> None:
        from widgets.screens.subagents_list import SubagentsListScreen
        app.push_screen(SubagentsListScreen())


class SubagentCommand(SubagentsCommand):
    name = "/subagent"


class DemoCommand(BaseCommand):
    name = "/demo"
    description = "Showcase all Markdown styles and UI widgets"

    async def execute(self, app) -> None:
        chat_view = app.query_one(ChatView)
        await chat_view.add_user_message("/demo — Showcase all Markdown & UI styles")

        tw = await chat_view.add_thinking_widget("Thinking about layout aesthetics...")
        tw.finish_thinking(0.4, "Analyzing Markdown CSS tokens, H1-H6 headers, code block syntax themes, and table borders.")

        await chat_view.add_tool_call("read", "/Users/yegor/testing/snake.html", result_text="1 | <!DOCTYPE html> ...")
        await chat_view.add_tool_call("edit", "core/config.py", result_text="Updated styles")
        await chat_view.add_tool_call("bash", "uv run pytest", result_text="107 passed in 0.9s")

        bot_msg = await chat_view.add_bot_message()
        bot_msg.content = (
            "# Heading 1 (H1)\n"
            "## Heading 2 (H2)\n"
            "### Heading 3 (H3)\n"
            "#### Heading 4 (H4)\n"
            "##### Heading 5 (H5)\n\n"
            "---\n\n"
            "### Text Formatting\n"
            "Standard text. **Bold text**. *Italic text*. ~~Strikethrough~~. Inline code: `const x = 42;`.\n\n"
            "---\n\n"
            "### Lists\n"
            "* Bullet item 1\n"
            "* Bullet item 2\n"
            "  * Nested item A\n"
            "  * Nested item B\n\n"
            "1. Numbered item 1\n"
            "2. Numbered item 2\n\n"
            "- [x] Completed task\n"
            "- [ ] Pending task\n\n"
            "---\n\n"
            "### Blockquote\n"
            "> This is a blockquote element in Johnston Chat UI.\n\n"
            "---\n\n"
            "### Table\n"
            "| Element | Type | Status |\n"
            "| :--- | :---: | ---: |\n"
            "| H1..H6 | Header | Active |\n"
            "| Table | Layout | Active |\n"
            "| Code | Highlight | Active |\n\n"
            "---\n\n"
            "### Code Blocks\n"
            "```javascript\n"
            "const x = 42;\n"
            "```\n\n"
            "```python\n"
            "def check_styles():\n"
            "    return 'Markdown ready!'\n"
            "```\n\n"
            "```bash\n"
            "uv run python -m unittest\n"
            "```\n"
        )
        await chat_view.add_compaction_divider("Session Compacted Sample")
        app.notify("Markdown & UI showcase rendered!")


class MarkdownCommand(DemoCommand):
    name = "/markdown"
    description = "Showcase all Markdown styles (alias for /demo)"


class StylesCommand(DemoCommand):
    name = "/styles"
    description = "Showcase all UI styles (alias for /demo)"


COMMAND_CLASSES = [
    HelpCommand,
    NewCommand,
    ConnectCommand,
    ProviderCommand,
    ModelsCommand,
    RewindCommand,
    ResumeCommand,
    TasksCommand,
    SubagentsCommand,
    SubagentCommand,
    SkillsCommand,
    MCPCommand,
    InitCommand,
    CompactCommand,
    ActionCommand,
    ExploreCommand,
    PlanCommand,
    BuildCommand,
    CodeCommand,
    AskCommand,
    DebugCommand,
    OrchestratorCommand,
    ModeCommand,
    PasteCommand,
    CopyCommand,
    TestModalCommand,
    DemoCommand,
    MarkdownCommand,
    StylesCommand,
]

COMMAND_REGISTRY = {
    cls.name: cls
    for cls in COMMAND_CLASSES
}

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

    if normalized_name in COMMAND_REGISTRY:
        cmd_instance = COMMAND_REGISTRY[normalized_name]()
        await cmd_instance.execute(app)
        return True
    return False
