import asyncio
import logging

from textual import events, work

from widgets.app.dispatch import handle_slash_command
from widgets.chat_input import ChatInput
from widgets.presentation.widgets.chat_container import ChatView
from widgets.status_footer import StatusFooter

logger = logging.getLogger(__name__)


def _register_tool_widget(mixin):
    """Return a callback that stores the created tool widget on the mixin."""

    def _cb(widget):
        mixin.current_tool_widget = widget
        return widget

    return _cb


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

    async def _exec_slash_command(self, user_text: str) -> None:
        try:
            processed = await handle_slash_command(self, user_text)
            if not processed:
                if user_text.startswith("/") and len(user_text.split()) == 1:
                    self.notify("Unknown command", severity="warning")
                else:
                    if self.is_generating:
                        self._queue_message_ui(user_text, show_in_ui=True)
                    else:
                        self.trigger_ai_response(user_text, show_in_ui=True)
        except Exception as e:
            self.notify(f"Command execution failed: {e}", severity="error")

    def _queue_message_ui(self, prompt: str, show_in_ui: bool = True, attachments: list = None) -> None:
        """Queue message to be executed after current generation finishes."""
        curr_sid = getattr(self, "current_session_id", None)
        item = (prompt, show_in_ui, attachments, curr_sid) if attachments else (prompt, show_in_ui, None, curr_sid)
        self.message_queue.append(item)
        if show_in_ui:
            try:
                self.notify("Message queued", severity="info")
            except Exception as e:
                logger.warning("Notify failed: %s", e)

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle input and slash commands (/help, /new, /skills)"""
        user_text = event.value.strip()
        attachments = getattr(event, "attachments", [])
        if not user_text and not attachments:
            return

        if user_text and user_text.startswith("/"):
            asyncio.create_task(self._exec_slash_command(user_text))
            return

        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        if not user_text and attachments:
            user_text = "What is in this image?"

        kwargs = {"attachments": attachments} if attachments else {}
        if self.is_generating:
            self._queue_message_ui(user_text, show_in_ui=True, attachments=attachments)
        else:
            self.trigger_ai_response(user_text, show_in_ui=True, **kwargs)

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False, attachments: list = None) -> None:
        """Safely trigger AI response generation, or queue prompt if currently generating."""
        if getattr(self, "is_generating", False):
            self._queue_message_ui(prompt, show_in_ui=show_in_ui, attachments=attachments)
        else:
            self.is_generating = True
            kwargs = {"attachments": attachments} if attachments else {}
            self.generate_ai_response(prompt, show_in_ui=show_in_ui, **kwargs)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str, show_in_ui: bool = True, attachments: list = None) -> None:
        """Stream AI response generation with cancellation support via Esc.

        Thin wrapper that builds a GenCanvas and delegates to the engine.
        """
        from core.application.generation.ai_generator import ProviderReadyState, ensure_provider_ready

        # ---- connectivity check (mixin-level) ----
        state = ensure_provider_ready(self.pm, self.agent)
        if state is not ProviderReadyState.READY:
            if state is ProviderReadyState.NEEDS_PROVIDER:
                from widgets.commands import ProvidersCommand

                await ProvidersCommand().execute(self)
            else:
                from widgets.commands import ModelsCommand

                await ModelsCommand().execute(self)
            self.is_generating = False
            return

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
            )
        except asyncio.CancelledError:
            # The engine raises CancelledError outwards after cleaning up
            # partial widgets. We just need to reset mixin-level state and
            # drain the queue.
            pass
        except Exception as e:
            # The engine already called canvas.notify for generic exceptions.
            logger.warning("AI generation failed: %s", e)
        finally:
            try:
                footer = self.query_one("#status-footer", StatusFooter)
                footer.set_generating(False)
            except Exception as e:
                logger.warning("Footer update failed: %s", e)
            try:
                if getattr(self, "is_app_active", True):
                    # Non-forced save: respects the built-in 1.5s debounce so the
                    # per-tool_result saves in the engine still coalesce here
                    # instead of forcing a full write on every tool call.
                    await self.save_current_session_async()
            except Exception as e:
                logger.warning("Session save failed: %s", e)
            self.is_generating = False
            if getattr(self, "is_app_active", True):
                next_item = self._pop_queued_for_current_session()
                if next_item is not None:
                    asyncio.create_task(self._process_queued_message(next_item[0], next_item[1], next_item[2]))

    def _pop_queued_for_current_session(self):
        """Pop the first queued message bound to the current session, or None."""
        curr_sid = getattr(self, "current_session_id", None)
        for idx, item in enumerate(self.message_queue):
            item_sid = item[3] if len(item) > 3 else None
            if item_sid is None or curr_sid is None or item_sid == curr_sid:
                return self.message_queue.pop(idx)
        return None

    async def _process_queued_message(self, prompt, show_in_ui=True, attachments=None) -> None:
        """Run a queued message on the next event-loop iteration after the @work task."""
        await asyncio.sleep(0)
        self.trigger_ai_response(prompt, show_in_ui=show_in_ui, attachments=attachments)

    def on_background_shell_completed(self, task_id: str, command_str: str, result: str) -> None:
        """Callback when background shell command finishes.

        Updates the linked tool widget's status (spinner -> done/error) so the
        card no longer stays yellow after the process exits.
        """
        if not getattr(self, "is_app_active", True):
            return
        try:
            self._update_background_shell_widget(task_id, result)
            from tools.base import format_background_notification, truncate_output

            msg = format_background_notification(
                "Background shell",
                command_str,
                task_id,
                truncate_output(
                    result,
                    max_chars=4000,
                    hint="Pipe output to grep/head/tail if complete log is needed.",
                    tool_name="shell",
                    from_end=True,
                    save_log=False,
                ),
            )
            curr_sid = getattr(self, "current_session_id", None)
            if self.is_generating:
                self.message_queue.append((msg, False, None, curr_sid))
            else:
                self.generate_ai_response(msg, show_in_ui=False)
        except Exception as e:
            logger.warning("Background completion handling failed: %s", e)

    def _update_background_shell_widget(self, task_id: str, result: str) -> None:
        """Repaint the linked shell tool card once a background task finishes.

        The widget keeps the ``running`` (yellow) status until here; we flip it
        based on the shell task's terminal status. No-op when the task or its
        widget is unavailable.
        """
        mgr = getattr(self, "task_manager", None)
        if mgr is None:
            return
        task = next(
            (t for t in mgr if getattr(t, "task_id", None) == task_id and getattr(t, "kind", "") == "shell"),
            None,
        )
        widget = getattr(task, "widget", None) if task is not None else None
        if widget is None:
            return
        try:
            task_status = (getattr(getattr(task, "status"), "value", None) or "").lower()
            status = "error" if task_status == "error" else ("done" if task_status in ("completed", "killed", "timeout") else None)
            if status is not None:
                widget.set_result(result or "(no output)", status=status)
        except Exception as e:
            logger.warning("Background shell widget update failed: %s", e)

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        """Callback when a background subagent finishes.

        Repaints the linked invoke_subagent tool card (yellow running) to its
        terminal color: green (done), red (error), or red/struck (cancelled).
        """
        if not getattr(self, "is_app_active", True):
            return
        try:
            reg = getattr(self, "_subagent_tools", None)
            widget = reg.get(session_id) if isinstance(reg, dict) else None
            if widget is None:
                return
            status = (status or "").lower()
            if status == "cancelled":
                widget.mark_cancelled()
            elif status == "error":
                widget.set_result(result or "(no output)", status="error")
            else:
                widget.set_result(result or "(no output)", status="done")
        except Exception as e:
            logger.warning("Subagent tool completion handling failed: %s", e)
