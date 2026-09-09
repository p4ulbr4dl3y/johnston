"""Textual-based inline REPL for Johnston (`j`) matching Claude Code CLI."""
from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Any, Optional

from rich.console import Console
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from johnston_cli.repl.commands import CommandHandler
from johnston_cli.repl.engine.events import (
    TextChunkEvent,
    ThinkingDoneEvent,
    ThinkingStartEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    TurnDoneEvent,
)
from johnston_cli.repl.engine.mock import MockEngine
from johnston_cli.repl.engine.protocol import ReplEngine
from johnston_cli.repl.render import ReplRenderer, is_tool_expandable, render_thinking, render_tool_call
from johnston_cli.repl.session import ReplSession

SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class ThinkingWidget(Static):
    """Widget displaying completed thinking with optional expandable reasoning."""

    def __init__(
        self,
        event: ThinkingDoneEvent,
        expanded: bool = False,
        show_hint: bool = True,
        **kwargs: Any,
    ) -> None:
        self.event = event
        self.expanded = expanded
        self.show_hint = show_hint
        super().__init__(
            render_thinking(self.event, expanded=self.expanded, show_hint=self.show_hint),
            **kwargs,
        )

    def set_expanded(self, expanded: bool) -> None:
        if self.event.content and self.expanded != expanded:
            self.expanded = expanded
            self.update(render_thinking(self.event, expanded=self.expanded, show_hint=self.show_hint))

    def set_show_hint(self, show: bool) -> None:
        if self.show_hint != show:
            self.show_hint = show
            self.update(render_thinking(self.event, expanded=self.expanded, show_hint=self.show_hint))


class ToolCallWidget(Static):
    """Widget displaying a tool call with optional expandable details."""

    def __init__(
        self,
        event: ToolCallResultEvent,
        expanded: bool = False,
        show_hint: bool = True,
        is_sequential: bool = False,
        **kwargs: Any,
    ) -> None:
        self.event = event
        self.expanded = expanded
        self.show_hint = show_hint
        self.is_sequential = is_sequential
        classes = kwargs.pop("classes", "")
        if is_sequential and not expanded:
            classes = f"{classes} -sequential".strip()
        super().__init__(
            render_tool_call(self.event, expanded=self.expanded, show_hint=self.show_hint),
            classes=classes,
            **kwargs,
        )

    def set_expanded(self, expanded: bool) -> None:
        if is_tool_expandable(self.event.tool_name) and self.expanded != expanded:
            self.expanded = expanded
            self.sync_sequential()
            self.update(render_tool_call(self.event, expanded=self.expanded, show_hint=self.show_hint))

    def set_show_hint(self, show: bool) -> None:
        if self.show_hint != show:
            self.show_hint = show
            self.update(render_tool_call(self.event, expanded=self.expanded, show_hint=self.show_hint))

    def sync_sequential(self) -> None:
        if self.is_sequential and not self.expanded:
            self.add_class("-sequential")
        else:
            self.remove_class("-sequential")


def _get_git_branch() -> Optional[str]:
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _shorten_path(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


class ReplApp(App[int]):
    """Claude Code-style REPL using Textual inline mode with native mouse selection."""

    AUTO_FOCUS = "#prompt-input"

    CSS = """
    Screen {
        height: auto;
        max-height: 100%;
        background: ansi_default;
        border: none;
    }
    Screen:inline {
        border: none;
    }
    #repl-banner {
        background: ansi_default;
        padding: 0;
        margin: 0 0 1 0;
    }
    #chat-container {
        height: auto;
        overflow-y: auto;
        scrollbar-size-vertical: 0;
        background: ansi_default;
        padding: 0;
        margin: 0;
    }
    ThinkingWidget {
        height: auto;
        background: ansi_default;
        margin: 1 0 0 0;
        padding: 0;
    }
    ToolCallWidget {
        height: auto;
        background: ansi_default;
        margin: 1 0 0 0;
        padding: 0;
    }
    ToolCallWidget.-sequential {
        margin: 0;
    }
    .bot-response {
        margin: 1 0 0 0;
        padding: 0 0 0 2;
    }
    Input#prompt-input {
        border: round #3f3f46;
        border-subtitle-color: #71717a;
        background: ansi_default;
        padding: 0 1;
        height: 3;
        margin: 0;
    }
    Input#prompt-input:focus {
        border: round #52525b;
        background: ansi_default;
    }
    Input#prompt-input.-generating {
        border: round #d4a259;
        border-subtitle-color: #d4a259;
    }
    Input#prompt-input > .input--cursor {
        background: #ffffff;
        color: #18181b;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "handle_ctrl_c", "Cancel / Exit", show=False),
        Binding("ctrl+d", "exit_app", "Exit", show=False),
        Binding("ctrl+o", "toggle_tools", "Toggle tools", show=False),
        Binding("pageup", "scroll_page_up", "Scroll page up", show=False),
        Binding("pagedown", "scroll_page_down", "Scroll page down", show=False),
        Binding("shift+up", "scroll_line_up", "Scroll line up", show=False),
        Binding("shift+down", "scroll_line_down", "Scroll line down", show=False),
        Binding("home", "scroll_home", "Scroll top", show=False),
        Binding("end", "scroll_end", "Scroll bottom", show=False),
    ]

    def __init__(
        self,
        engine: Optional[ReplEngine] = None,
        model: Optional[str] = None,
        role: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.theme = "ansi-dark"
        self.ansi_color = True
        self.session = ReplSession(
            model_name=model or "claude-3-7-sonnet",
            role=role or "assistant",
        )
        self.console = Console(highlight=False)
        self.renderer = ReplRenderer(self.console)
        self.commands = CommandHandler(
            console=self.console,
            output_func=self._on_command_output,
            clear_func=self._clear_chat,
        )
        self.engine: ReplEngine = engine or MockEngine()
        self.is_mock = isinstance(self.engine, MockEngine)
        self.initial_prompt = initial_prompt

        self._prompt_queue: asyncio.Queue[str] = asyncio.Queue()
        self._is_generating: bool = False
        self._tools_expanded: bool = False
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._turn_task: Optional[asyncio.Task[None]] = None

    def _build_welcome_banner(self) -> str:
        branch = _get_git_branch()
        branch_str = f" · [#5ea876]{branch}[/#5ea876]" if branch else ""
        cwd_str = _shorten_path(os.getcwd())
        mode_str = " [dim](mock)[/dim]" if self.is_mock else ""

        lines = [
            "  [bold #61afef]▄████[/bold #61afef]  [bold white]Johnston[/bold white] [dim]v0.1.0[/dim]",
            f"     [bold #61afef]██[/bold #61afef]  [white]{self.session.model_name}[/white]{mode_str}",
            f"  [bold #61afef]▄  ██[/bold #61afef]  [dim]{cwd_str}[/dim]{branch_str}",
            "  [bold #61afef]████▀[/bold #61afef]  [dim]/help for commands[/dim]",
        ]
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Static(self._build_welcome_banner(), id="repl-banner"),
            id="chat-container",
        )
        inp = Input(
            placeholder="❯ Type a prompt or /help...",
            id="prompt-input",
        )
        inp.border_subtitle = self._format_footer()
        inp.border_subtitle_align = "left"
        yield inp

    def _format_footer(self) -> str:
        if self._is_generating:
            return " ⠙ Generating... (Ctrl+C to cancel) "
        if self._tools_expanded:
            return f" {self.session.model_name} · ctrl+o to collapse · PgUp/PgDn to scroll "
        if self.session.total_tokens == 0:
            return " ? help · / commands "
        cost = self.session.total_cost_usd
        tokens = self.session.total_tokens
        return f" {self.session.model_name} · {tokens:,} tokens (${cost:.3f}) · ? help "

    def _update_footer(self) -> None:
        if self.is_mounted:
            try:
                inp = self.query_one("#prompt-input", Input)
                inp.border_subtitle = self._format_footer()
                if self._is_generating:
                    inp.add_class("-generating")
                else:
                    inp.remove_class("-generating")
            except Exception:
                pass

    def _clear_chat(self) -> None:
        if self.is_mounted:
            try:
                container = self.query_one("#chat-container", VerticalScroll)
                container.remove_children()
            except Exception:
                pass

    def _on_command_output(self, renderable: Any) -> None:
        if self.is_mounted:
            try:
                container = self.query_one("#chat-container", VerticalScroll)
                container.mount(Static(renderable, classes="bot-response"))
                container.scroll_end(animate=False)
                return
            except Exception:
                pass
        self.console.print(renderable)

    def on_resize(self, event: events.Resize) -> None:
        self._sync_container_height()

    def _sync_container_height(self) -> None:
        if self.is_mounted:
            try:
                container = self.query_one("#chat-container", VerticalScroll)
                max_h = max(1, self.size.height - 3)
                container.styles.max_height = max_h
            except Exception:
                pass

    async def on_mount(self) -> None:
        self._sync_container_height()
        self._worker_task = asyncio.create_task(self._worker_loop())
        try:
            self.query_one("#prompt-input", Input).focus()
        except Exception:
            pass
        if self.initial_prompt:
            await self._prompt_queue.put(self.initial_prompt)

    async def on_unmount(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()

    def action_handle_ctrl_c(self) -> None:
        """Handle Ctrl+C: cancel generation if running, else exit."""
        if self._is_generating and self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
        else:
            self.exit(0)

    def action_exit_app(self) -> None:
        """Handle Ctrl+D to exit."""
        self.exit(0)

    def action_scroll_page_up(self) -> None:
        """Scroll chat up by one page."""
        if self.is_mounted:
            try:
                self.query_one("#chat-container", VerticalScroll).scroll_page_up(animate=False)
            except Exception:
                pass

    def action_scroll_page_down(self) -> None:
        """Scroll chat down by one page."""
        if self.is_mounted:
            try:
                self.query_one("#chat-container", VerticalScroll).scroll_page_down(animate=False)
            except Exception:
                pass

    def action_scroll_line_up(self) -> None:
        """Scroll chat up by a few lines."""
        if self.is_mounted:
            try:
                self.query_one("#chat-container", VerticalScroll).scroll_relative(y=-3, animate=False)
            except Exception:
                pass

    def action_scroll_line_down(self) -> None:
        """Scroll chat down by a few lines."""
        if self.is_mounted:
            try:
                self.query_one("#chat-container", VerticalScroll).scroll_relative(y=3, animate=False)
            except Exception:
                pass

    def action_scroll_home(self) -> None:
        """Scroll chat to the top."""
        if self.is_mounted:
            try:
                self.query_one("#chat-container", VerticalScroll).scroll_home(animate=False)
            except Exception:
                pass

    def action_scroll_end(self) -> None:
        """Scroll chat to the bottom."""
        if self.is_mounted:
            try:
                self.query_one("#chat-container", VerticalScroll).scroll_end(animate=False)
            except Exception:
                pass

    def _update_expand_hints(self) -> None:
        """Ensure (ctrl+o to expand/collapse) hint is shown only on the last expandable widget."""
        if not self.is_mounted:
            return
        try:
            container = self.query_one("#chat-container", VerticalScroll)
            expandables: list[ThinkingWidget | ToolCallWidget] = []
            for child in container.children:
                if isinstance(child, ThinkingWidget) and child.event.content:
                    expandables.append(child)
                elif isinstance(child, ToolCallWidget) and is_tool_expandable(child.event.tool_name):
                    expandables.append(child)

            for w in expandables[:-1]:
                w.set_show_hint(False)
            if expandables:
                expandables[-1].set_show_hint(True)
        except Exception:
            pass

    def action_toggle_tools(self) -> None:
        """Toggle expansion of expandable tool calls and thinking."""
        self._tools_expanded = not self._tools_expanded
        if self.is_mounted:
            try:
                container = self.query_one("#chat-container", VerticalScroll)
                for widget in container.query(ToolCallWidget):
                    widget.set_expanded(self._tools_expanded)
                for widget in container.query(ThinkingWidget):
                    widget.set_expanded(self._tools_expanded)
                self._update_expand_hints()
                self._update_footer()
                if self._tools_expanded:
                    container.scroll_home(animate=False)
                else:
                    container.scroll_end(animate=False)
            except Exception:
                pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        event.input.focus()
        if not text:
            return

        if self.commands.is_command(text):
            should_exit = self.commands.handle(text, self.session)
            if should_exit:
                self.exit(0)
            return

        if self._is_generating:
            await self._prompt_queue.put(text)
            if self.is_mounted:
                try:
                    container = self.query_one("#chat-container", VerticalScroll)
                    await container.mount(
                        Static(f"[dim yellow]⠙ Queued #{self._prompt_queue.qsize()}: {text}[/dim yellow]\n")
                    )
                    container.scroll_end(animate=False)
                except Exception:
                    pass
        else:
            await self._prompt_queue.put(text)

    async def _run_turn(self, prompt: str) -> None:
        """Execute a single prompt turn, mounting events into the chat container."""
        container: Optional[VerticalScroll] = None
        status_widget: Optional[Static] = None

        if self.is_mounted:
            try:
                container = self.query_one("#chat-container", VerticalScroll)
                await container.mount(Static(f"[bold cyan]❯[/bold cyan] [bold white]{prompt}[/bold white]\n"))
                status_widget = Static("[dim]⠋ Thinking...[/dim]")
                await container.mount(status_widget)
                container.scroll_end(animate=False)
            except Exception:
                pass

        accumulated_text: list[str] = []
        response_widget: Optional[Static] = None
        tokens_added = 0
        cost_added = 0.0

        current_status = "Thinking..."
        start_time = asyncio.get_running_loop().time()
        spinner_running = True

        async def _animate_spinner() -> None:
            idx = 0
            while spinner_running:
                if status_widget is not None and self.is_mounted:
                    elapsed = asyncio.get_running_loop().time() - start_time
                    frame = SPINNER_FRAMES[idx % len(SPINNER_FRAMES)]
                    status_widget.update(f"[dim]{frame} {current_status} ({elapsed:.1f}s)[/dim]")
                idx += 1
                try:
                    await asyncio.sleep(0.08)
                except asyncio.CancelledError:
                    break

        spinner_task = asyncio.create_task(_animate_spinner())

        try:
            async for event in self.engine.generate(prompt, self.session):
                if isinstance(event, ThinkingStartEvent):
                    current_status = "Thinking..."

                elif isinstance(event, ThinkingDoneEvent):
                    spinner_running = False
                    spinner_task.cancel()
                    if status_widget is not None:
                        status_widget.remove()
                        status_widget = None
                    if container is not None:
                        thinking_widget = ThinkingWidget(event, expanded=self._tools_expanded)
                        await container.mount(thinking_widget)
                        self._update_expand_hints()
                        container.scroll_end(animate=False)

                elif isinstance(event, ToolCallStartEvent):
                    current_status = f"Running {event.tool_name}..."

                elif isinstance(event, ToolCallResultEvent):
                    if container is not None:
                        is_seq = False
                        if container.children:
                            prev_child = container.children[-1]
                            if isinstance(prev_child, ToolCallWidget):
                                is_seq = True
                        tool_widget = ToolCallWidget(
                            event,
                            expanded=self._tools_expanded,
                            is_sequential=is_seq,
                        )
                        await container.mount(tool_widget)
                        self._update_expand_hints()
                        container.scroll_end(animate=False)

                elif isinstance(event, TextChunkEvent):
                    accumulated_text.append(event.text)
                    if container is not None:
                        if response_widget is None:
                            response_widget = Static("", classes="bot-response")
                            await container.mount(response_widget)
                        response_widget.update("".join(accumulated_text))
                        container.scroll_end(animate=False)

                elif isinstance(event, TurnDoneEvent):
                    tokens_added = event.added_tokens
                    cost_added = event.estimated_cost_usd

            if container is not None:
                await container.mount(Static(""))

            self.session.record_turn(
                prompt=prompt,
                response="".join(accumulated_text),
                tokens=tokens_added,
                cost=cost_added,
            )
            self._update_footer()

        except asyncio.CancelledError:
            if container is not None:
                await container.mount(Static("\n[dim yellow]Turn cancelled by user.[/dim yellow]\n"))
        except Exception as e:
            if container is not None:
                await container.mount(Static(f"\n[bold red]Error in generation:[/bold red] {e}\n"))
        finally:
            spinner_running = False
            spinner_task.cancel()
            if container is not None:
                container.scroll_end(animate=False)

    async def _worker_loop(self) -> None:
        """Worker executing queued prompts sequentially."""
        while True:
            try:
                prompt = await self._prompt_queue.get()
                self._is_generating = True
                self._turn_task = asyncio.current_task()
                self._update_footer()
                try:
                    await self._run_turn(prompt)
                finally:
                    self._is_generating = False
                    self._turn_task = None
                    self._update_footer()
                    self._prompt_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.is_mounted:
                    try:
                        container = self.query_one("#chat-container", VerticalScroll)
                        await container.mount(Static(f"\n[bold red]Error in worker:[/bold red] {e}\n"))
                    except Exception:
                        pass

    def run(self, initial_prompt: Optional[str] = None, **kwargs: Any) -> int:
        """Run the REPL in Textual inline mode with native mouse selection."""
        if initial_prompt:
            self.initial_prompt = initial_prompt
        kwargs.setdefault("inline", True)
        kwargs.setdefault("mouse", False)
        kwargs.setdefault("inline_no_clear", True)
        super().run(**kwargs)
        return 0

    async def run_async(self, initial_prompt: Optional[str] = None, **kwargs: Any) -> int:
        """Run the REPL asynchronously in Textual inline mode."""
        if initial_prompt:
            self.initial_prompt = initial_prompt
        kwargs.setdefault("inline", True)
        kwargs.setdefault("mouse", False)
        kwargs.setdefault("inline_no_clear", True)
        await super().run_async(**kwargs)
        return 0


__all__ = ["ReplApp", "ThinkingWidget", "ToolCallWidget"]
