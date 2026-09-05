import asyncio
import logging
from typing import Any, Optional

from textual import events, work

from widgets.app.dispatch import handle_slash_command
from widgets.chat_input import DEFAULT_PLACEHOLDER, ChatInput
from widgets.mixins.message_flow_background import (
    on_background_shell_completed,
    on_background_shell_progress,
    on_subagent_tool_completed,
    schedule_session_save,
    update_background_shell_widget,
)
from widgets.presentation.widgets.chat_container import ChatView
from widgets.status_footer import StatusFooter

logger = logging.getLogger(__name__)


def _register_tool_widget(mixin):
    """Return a callback that stores the created tool widget on the mixin."""

    def _cb(widget):
        mixin.current_tool_widget = widget
        return widget

    return _cb


def _cancel_parent_subagents(mixin):
    """Return a sync callback cancelling subagents spawned by this parent session.

    Used as the engine canvas ``cancel_subagents`` hook on interruption (Esc,
    /stop). Lazily imports the core helper (avoiding any import cycle) and
    swallows failures; cancellation must never raise.
    """

    def _cancel(session_id: str) -> None:
        try:
            from core.application.session.stream import cancel_running_subagents

            store = getattr(mixin, "sm", None)
            if store is not None:
                cancel_running_subagents(store, parent_id=session_id)
        except Exception:  # noqa: BLE001
            logger.debug("Subagent cancellation on interrupt failed", exc_info=True)

    return _cancel


class MessageFlowMixin:

    """Chat input handling, AI response generation and message queueing for JohnstonApp."""

    async def on_paste(self, event: events.Paste) -> None:
        """Forward application-level paste/drag-and-drop events to ChatInput"""
        try:
            chat_input = self.query_one("#message-input", ChatInput)
            chat_input.focus()
            await chat_input.on_paste(event)
        except Exception:
            pass

    async def _exec_slash_command(self, user_text: str, attachments: list = None) -> None:
        try:
            if attachments:
                processed = await handle_slash_command(self, user_text, attachments=attachments)
            else:
                processed = await handle_slash_command(self, user_text)
            if not processed:
                if user_text.startswith("/") and len(user_text.split()) == 1:
                    self.notify("Unknown command", severity="warning")
                    if attachments:
                        try:
                            ci = self.query_one("#message-input", ChatInput)
                            ci.clipboard_attachments = list(attachments)
                            ci.update_attachment_bar()
                        except Exception:
                            pass
                else:
                    if self.is_generating:
                        self._queue_message_ui(user_text, show_in_ui=True, attachments=attachments)
                    else:
                        kwargs = {"attachments": attachments} if attachments else {}
                        self.trigger_ai_response(user_text, show_in_ui=True, **kwargs)
        except Exception as e:
            self.notify(f"Command execution failed: {e}", severity="error")
            if attachments:
                try:
                    ci = self.query_one("#message-input", ChatInput)
                    ci.clipboard_attachments = list(attachments)
                    ci.update_attachment_bar()
                except Exception:
                    pass

    async def _exec_shell_command(self, cmd: str, user_text: str = None) -> None:
        """Execute a user shell command (!cmd) directly without calling LLM."""
        try:
            chat_input = self.query_one("#message-input", ChatInput)
            chat_input.focus()
        except Exception:
            pass

        self._apply_pending_fork_or_readonly()

        full_prompt = user_text or f"!{cmd}"
        from widgets.presentation.widgets.chat_container import ChatView

        chat_view = self.query_one(ChatView)
        if hasattr(chat_view, "clear_welcome"):
            chat_view.clear_welcome()

        # Mount user message in UI
        await chat_view.add_user_message(full_prompt)

        # Record user event to active session
        session = None
        if hasattr(self, "sm") and hasattr(self, "current_session_id") and self.current_session_id:
            session = self.sm.get(self.current_session_id, reload=False) or self.sm.create_main(self.current_session_id)
        elif hasattr(self, "session"):
            session = self.session

        if session is not None and hasattr(session, "add_event"):
            session.add_event({"type": "user", "text": full_prompt})
            if hasattr(self, "save_current_session_async"):
                await self.save_current_session_async(force=True)
            elif hasattr(self, "save_current_session"):
                self.save_current_session()

        # Mount running tool call widget
        tool_widget = await chat_view.add_tool_call(
            tool_type="shell",
            target=cmd,
            args={"command": cmd},
            status="running",
        )

        from tools.context import ToolContext
        from tools.shell import ShellTool

        ctx = ToolContext(self)
        tool = ShellTool()
        self.current_tool_widget = tool_widget
        try:
            res = await tool.execute({"command": cmd}, ctx=ctx)
            content = res.content or ""
            returncode = getattr(res, "returncode", None)
            is_error = getattr(res, "is_error", False) or (returncode is not None and returncode != 0)
            res_status = getattr(res, "status", None)
            if hasattr(res_status, "value"):
                status = res_status.value
            elif isinstance(res_status, str):
                status = res_status
            else:
                status = "error" if is_error else "done"
        except Exception as e:
            content = f"ERR: {e}"
            returncode = 1
            is_error = True
            status = "error"
        finally:
            self.current_tool_widget = None

        if tool_widget is not None:
            tool_widget.set_result(content, is_error=is_error, status=status, returncode=returncode)
            if hasattr(tool_widget, "render_header"):
                tool_widget.render_header()
            if hasattr(tool_widget, "render_content"):
                tool_widget.render_content()

        if session is not None and hasattr(session, "add_event"):
            session.add_event({
                "type": "tool",
                "tool_type": "shell",
                "target": cmd,
                "result_text": content,
                "args": {"command": cmd},
                "status": status,
                "returncode": returncode,
            })

        agent = getattr(self, "agent", None)
        if agent is not None and hasattr(agent, "history") and isinstance(agent.history, list):
            history_text = f"! {cmd}\n\n{content}".rstrip() if content else f"! {cmd}"
            agent.history.append({"role": "user", "content": history_text})

        if hasattr(self, "save_current_session_async"):
            await self.save_current_session_async(force=True)
        elif hasattr(self, "save_current_session"):
            self.save_current_session()

        if getattr(self, "is_app_active", True) and not getattr(self, "is_generating", False):
            next_item = self._pop_queued_for_current_session()
            if next_item is not None:
                kw = {}
                if len(next_item) > 4 and next_item[4]:
                    kw["display_text"] = next_item[4]
                asyncio.create_task(
                    self._process_queued_message(
                        next_item[0],
                        next_item[1],
                        next_item[2],
                        **kw,
                    )
                )

    def _queue_message_ui(
        self, prompt: str, show_in_ui: bool = True, attachments: list = None, display_text: str = None
    ) -> None:
        """Queue message to be executed after current generation finishes."""
        curr_sid = getattr(self, "current_session_id", None)
        if display_text:
            item = (prompt, show_in_ui, attachments, curr_sid, display_text)
        elif attachments:
            item = (prompt, show_in_ui, attachments, curr_sid)
        else:
            item = (prompt, show_in_ui, None, curr_sid)
        self.message_queue.append(item)
        if show_in_ui:
            try:
                self.notify("Message queued", severity="information")
            except Exception as e:
                logger.warning("Notify failed: %s", e)

    def _apply_pending_fork_or_readonly(self) -> None:
        """Commit pending lazy fork or fork a read-only session on user input."""
        pending_fork = getattr(self, "pending_fork", None)
        if pending_fork and hasattr(self, "sm"):
            parent_sid = pending_fork.get("parent_session_id")
            up_to_idx = pending_fork.get("up_to_msg_index")
            fork_title = pending_fork.get("title")
            self.pending_fork = None
            forked = self.sm.fork_session(parent_sid, new_title=fork_title, up_to_msg_index=up_to_idx)
            if forked:
                old_sid = getattr(self, "current_session_id", None)
                if old_sid and old_sid != forked.id and hasattr(self.sm, "release_session_lock"):
                    self.sm.release_session_lock(old_sid)
                self.current_session_id = forked.id
                if hasattr(self.sm, "acquire_session_lock"):
                    self.sm.acquire_session_lock(forked.id)
                if hasattr(self.sm, "set_active_session_id"):
                    self.sm.set_active_session_id(forked.id)
                self.is_read_only = False
                try:
                    chat_input = self.query_one("#message-input", ChatInput)
                    chat_input.placeholder = DEFAULT_PLACEHOLDER
                    if hasattr(chat_input, "update_placeholder"):
                        chat_input.update_placeholder()
                except Exception:
                    pass
                if hasattr(self, "notify"):
                    self.notify("Session forked", severity="information", timeout=1.5)
                if hasattr(self, "refresh_status_footer"):
                    self.refresh_status_footer()
        elif getattr(self, "is_read_only", False) and hasattr(self, "sm"):
            curr_id = getattr(self, "current_session_id", None)
            if curr_id and hasattr(self.sm, "fork_session"):
                forked = self.sm.fork_session(curr_id)
                if forked:
                    old_sid = getattr(self, "current_session_id", None)
                    if old_sid and old_sid != forked.id and hasattr(self.sm, "release_session_lock"):
                        self.sm.release_session_lock(old_sid)
                    self.current_session_id = forked.id
                    if hasattr(self.sm, "acquire_session_lock"):
                        self.sm.acquire_session_lock(forked.id)
                    if hasattr(self.sm, "set_active_session_id"):
                        self.sm.set_active_session_id(forked.id)
                    self.is_read_only = False
                    try:
                        chat_input = self.query_one("#message-input", ChatInput)
                        chat_input.placeholder = DEFAULT_PLACEHOLDER
                        if hasattr(chat_input, "update_placeholder"):
                            chat_input.update_placeholder()
                    except Exception:
                        pass
                    if hasattr(self, "notify"):
                        self.notify("Session forked", severity="information", timeout=1.5)
                    if hasattr(self, "refresh_status_footer"):
                        self.refresh_status_footer()

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle input and slash commands (/help, /new, /skills)"""
        user_text = event.value.strip()
        attachments = getattr(event, "attachments", [])
        if not user_text and not attachments:
            return

        if user_text and user_text.startswith("/"):
            asyncio.create_task(self._exec_slash_command(user_text, attachments=attachments))
            return

        if user_text and user_text.startswith("!"):
            cmd = user_text[1:].strip()
            if not cmd:
                self.notify("No shell command specified", severity="warning")
                return
            if self.is_generating:
                self._queue_message_ui(user_text, show_in_ui=True, attachments=attachments)
            else:
                asyncio.create_task(self._exec_shell_command(cmd, user_text=user_text))
            return

        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        self._apply_pending_fork_or_readonly()

        if not user_text and attachments:
            user_text = "What is in this image?"

        # Clear completed plan notch upon new user interaction turn
        cur_plan = getattr(self, "current_plan", None)
        if isinstance(cur_plan, list) and cur_plan and all(isinstance(p, dict) and p.get("status") == "completed" for p in cur_plan):
            self.current_plan = None
            self.current_plan_explanation = ""
            try:
                from widgets.presentation.widgets.plan_notch import PlanNotch

                self.query_one(PlanNotch).clear_plan()
            except Exception:
                pass

        kwargs = {"attachments": attachments} if attachments else {}
        if self.is_generating:
            self._queue_message_ui(user_text, show_in_ui=True, attachments=attachments)
        else:
            self.trigger_ai_response(user_text, show_in_ui=True, **kwargs)

    def trigger_ai_response(
        self, prompt: str, show_in_ui: bool = False, attachments: list = None, **kwargs
    ) -> None:
        """Safely trigger AI response generation, or queue prompt if currently generating."""
        if getattr(self, "is_generating", False):
            self._queue_message_ui(prompt, show_in_ui=show_in_ui, attachments=attachments, **kwargs)
        else:
            self.is_generating = True
            kw = {}
            if attachments:
                kw["attachments"] = attachments
            kw.update(kwargs)
            self.generate_ai_response(prompt, show_in_ui=show_in_ui, **kw)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(
        self, user_text: str, show_in_ui: bool = True, attachments: list = None, display_text: str = None
    ) -> None:
        """Stream AI response generation with cancellation support via Esc.

        Thin wrapper that builds a GenCanvas and delegates to the engine.
        """
        from core.application.generation.ai_generator import ProviderReadyState, ensure_provider_ready

        # ---- connectivity check (mixin-level) ----
        state = ensure_provider_ready(self.pm, self.agent)
        if state is not ProviderReadyState.READY:
            if state is ProviderReadyState.NEEDS_PROVIDER:
                from widgets.presentation.commands import ProvidersCommand

                await ProvidersCommand().execute(self)
            else:
                from widgets.presentation.commands import ModelsCommand

                await ModelsCommand().execute(self)
            self.is_generating = False
            return

        self._apply_pending_fork_or_readonly()
        self.is_generating = True
        chat_view = self.query_one(ChatView)

        # Ensure the transcript session exists.
        session = self.sm.get(self.current_session_id, reload=False) or self.sm.create_main(self.current_session_id)

        # ---- build canvas ----
        project_path = getattr(self.sm, "project_path", None) if hasattr(self, "sm") else None
        from widgets.app.ai_controller import build_gen_canvas, run_ai_generation

        canvas = build_gen_canvas(
            chat_view,
            on_tool_widget=_register_tool_widget(self),
            refresh_status_footer=self.refresh_status_footer,
            notify=self.notify,
            save_session=lambda: self.save_current_session_async(),
            cancel_subagents=_cancel_parent_subagents(self),
        )

        # ---- pre-stream footer & CancelledError guard ----
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            footer.set_generating(True)
        except Exception as e:
            logger.warning("Footer update failed: %s", e)

        try:
            await run_ai_generation(
                self.agent,
                session,
                canvas,
                session_id=getattr(self, "current_session_id", None),
                user_text=user_text,
                show_in_ui=show_in_ui,
                attachments=attachments,
                project_path=project_path,
                display_text=display_text,
            )
        except asyncio.CancelledError:
            # The engine raises CancelledError outwards after cleaning up
            # partial widgets. We just need to reset mixin-level state and
            # drain the queue.
            pass
        except Exception as e:
            # The engine already called canvas.notify for generic exceptions;
            # this catches the exceptions the engine re-raises (e.g. RuntimeError).
            logger.exception("AI generation failed: %s", e)
        finally:
            try:
                footer = self.query_one("#status-footer", StatusFooter)
                footer.set_generating(False)
            except Exception as e:
                logger.warning("Footer update failed: %s", e)
            is_active = bool(
                getattr(self, "is_app_active", True)
                and not getattr(self, "_exit", False)
                and not getattr(self, "_closing", False)
                and not getattr(self, "_closed", False)
            )
            try:
                if is_active:
                    # Non-forced save: respects the built-in 1.5s debounce so the
                    # per-tool_result saves in the engine still coalesce here
                    # instead of forcing a full write on every tool call.
                    await self.save_current_session_async()
            except Exception as e:
                logger.warning("Session save failed: %s", e)
            self.is_generating = False
            should_auto_title = (
                is_active
                and session
                and not getattr(session, "auto_titled", False)
                and (not getattr(session, "_title", None) or getattr(session, "parent_id", None))
            )
            if should_auto_title:
                self._schedule_auto_title(session)
            if is_active:
                next_item = self._pop_queued_for_current_session()
                if next_item is not None:
                    kw = {}
                    if len(next_item) > 4 and next_item[4]:
                        kw["display_text"] = next_item[4]
                    asyncio.create_task(
                        self._process_queued_message(
                            next_item[0],
                            next_item[1],
                            next_item[2],
                            **kw,
                        )
                    )

    def _schedule_auto_title(self, session: Any) -> None:
        """Schedule background auto-titling for a session without blocking UI."""
        if (
            not getattr(self, "is_app_active", True)
            or getattr(self, "_exit", False)
            or getattr(self, "_closing", False)
            or getattr(self, "_closed", False)
        ):
            return
        if not session or getattr(session, "auto_titled", False):
            return
        if getattr(session, "_title", None) and not getattr(session, "parent_id", None):
            return

        async def _run() -> None:
            if (
                not getattr(self, "is_app_active", True)
                or getattr(self, "_exit", False)
                or getattr(self, "_closing", False)
                or getattr(self, "_closed", False)
            ):
                return
            try:
                from core.application.session.auto_title import auto_title_session

                agent = getattr(self, "agent", None)
                title = await auto_title_session(agent, session)
                if title:
                    if hasattr(self, "sm"):
                        self.sm.save(session)
                    if getattr(self, "is_app_active", True) and getattr(self, "current_session_id", None) == getattr(session, "id", None):
                        if hasattr(self, "refresh_status_footer"):
                            self.refresh_status_footer()
            except Exception as e:
                logger.debug("Background auto-titling failed: %s", e)

        asyncio.create_task(_run())

    def _pop_queued_for_current_session(self):
        """Pop the first queued message bound to the current session, or None."""
        curr_sid = getattr(self, "current_session_id", None)
        for idx, item in enumerate(self.message_queue):
            item_sid = item[3] if len(item) > 3 else None
            if item_sid is None or curr_sid is None or item_sid == curr_sid:
                return self.message_queue.pop(idx)
        return None

    async def _process_queued_message(self, prompt, show_in_ui=True, attachments=None, **kwargs) -> None:
        """Run a queued message on the next event-loop iteration after the @work task."""
        await asyncio.sleep(0)
        user_text = (prompt or "").strip()
        if user_text.startswith("!"):
            cmd = user_text[1:].strip()
            if cmd:
                asyncio.create_task(self._exec_shell_command(cmd, user_text=user_text))
                return
        self.trigger_ai_response(prompt, show_in_ui=show_in_ui, attachments=attachments, **kwargs)

    def on_background_shell_completed(self, task_id: str, command_str: str, result: str) -> None:
        """Callback when background shell command finishes."""
        on_background_shell_completed(self, task_id, command_str, result)

    def on_background_shell_progress(
        self,
        task_id: str,
        command_str: str,
        result: str,
        *,
        event: str = "inactivity",
        idle_seconds: Optional[int] = None,
    ) -> None:
        """Callback when background shell emits a progress notification (e.g. inactivity)."""
        on_background_shell_progress(
            self,
            task_id,
            command_str,
            result,
            event=event,
            idle_seconds=idle_seconds,
        )

    def _update_background_shell_widget(self, task_id: str, result: str) -> None:
        """Repaint the linked shell tool card once a background task finishes."""
        update_background_shell_widget(self, task_id, result)

    def _schedule_session_save(self, session: Any) -> None:
        """Persist a session off the event loop, holding the shared write lock."""
        schedule_session_save(self, session)

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        """Callback when a background subagent finishes."""
        on_subagent_tool_completed(self, session_id, status, result)

