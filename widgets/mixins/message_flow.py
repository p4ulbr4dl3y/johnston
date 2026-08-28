import asyncio
import logging
from typing import Any

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

        if getattr(self, "is_read_only", False) and hasattr(self, "sm"):
            curr_id = getattr(self, "current_session_id", None)
            if curr_id and hasattr(self.sm, "fork_session"):
                forked = self.sm.fork_session(curr_id)
                if forked:
                    self.current_session_id = forked.id
                    if hasattr(self.sm, "acquire_session_lock"):
                        self.sm.acquire_session_lock(forked.id)
                    if hasattr(self.sm, "set_active_session_id"):
                        self.sm.set_active_session_id(forked.id)
                    self.is_read_only = False
                    chat_input.placeholder = "Type a message or / for commands..."

        if not user_text and attachments:
            user_text = "What is in this image?"

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
        self.trigger_ai_response(prompt, show_in_ui=show_in_ui, attachments=attachments, **kwargs)

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

            mgr = getattr(self, "task_manager", None)
            task = None
            if mgr is not None:
                task = next(
                    (t for t in mgr if getattr(t, "task_id", None) == task_id and getattr(t, "kind", "") == "shell"),
                    None,
                )
            task_log = getattr(task, "log_path", None)

            msg = format_background_notification(
                "shell",
                command_str,
                task_id,
                truncate_output(
                    result,
                    max_chars=4000,
                    tool_name="shell",
                    from_end=True,
                    save_log=False,
                    log_path=task_log,
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
        task = None
        if mgr is not None:
            task = next(
                (t for t in mgr if getattr(t, "task_id", None) == task_id and getattr(t, "kind", "") == "shell"),
                None,
            )
        task_log = getattr(task, "log_path", None)

        from tools.base import truncate_output

        final_result = truncate_output(
            result or "(no output)",
            max_chars=4000,
            tool_name="shell",
            from_end=True,
            save_log=False,
            log_path=task_log,
        )
        reg = getattr(self, "_background_shell_widgets", None)
        widget = (reg or {}).pop(task_id, None)
        task_status = (getattr(getattr(task, "status", None), "value", None) or "").lower() if task is not None else ""
        status = "error" if task_status == "error" else ("done" if task_status in ("completed", "killed", "timeout") else "done")

        if widget is not None:
            try:
                widget.set_result(final_result, status=status)
            except Exception as e:
                logger.warning("Background shell widget update failed: %s", e)

        sid = getattr(self, "current_session_id", None)
        if sid and hasattr(self, "sm"):
            try:
                session = self.sm.get(sid, reload=False)
                if session:
                    for msg in session.messages:
                        if isinstance(msg, dict) and msg.get("type") == "tool" and task_id in msg.get("result_text", ""):
                            msg["result_text"] = final_result
                            msg["status"] = status
                            break
                    self._schedule_session_save(session)
            except Exception as e:
                logger.warning("Failed to update session for background shell %s: %s", task_id, e)

    def _schedule_session_save(self, session: Any) -> None:
        """Persist a session off the event loop, holding the shared write lock.

        Prefers the app's tracked-task scheduler so writes are awaited; falls back
        to spawning a task on the running loop, or to a direct save when no loop
        is running. Shared by the background-shell and subagent completion paths.
        """
        from widgets.mixins.session_persistence import _global_session_write_lock

        def _save_locked(s: Any) -> None:
            with _global_session_write_lock:
                self.sm.save(s)

        save_coro = asyncio.to_thread(_save_locked, session)
        if hasattr(self, "create_tracked_task") and callable(self.create_tracked_task):
            self.create_tracked_task(save_coro)
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(save_coro)
            except RuntimeError:
                _save_locked(session)

    def on_subagent_tool_completed(self, session_id: str, status: str, result: str = "") -> None:
        """Callback when a background subagent finishes.

        Repaints the linked invoke_subagent tool card (yellow running) to its
        terminal color: green (done), red (error), or red/struck (cancelled).
        """
        if not getattr(self, "is_app_active", True):
            return
        try:
            reg = getattr(self, "_subagent_tools", None)
            widget = reg.pop(session_id, None) if isinstance(reg, dict) else None
            status_clean = (status or "").lower()
            if widget is not None:
                if status_clean == "cancelled":
                    widget.mark_cancelled()
                elif status_clean == "error":
                    widget.set_result(result or "(no output)", status="error")
                else:
                    widget.set_result(result or "(no output)", status="done")

            final_status = "error" if status_clean == "error" else ("cancelled" if status_clean == "cancelled" else "done")
            sid = getattr(self, "current_session_id", None)
            if sid and hasattr(self, "sm"):
                session = self.sm.get(sid, reload=False)
                if session:
                    for msg in session.messages:
                        if isinstance(msg, dict) and msg.get("type") == "tool" and msg.get("tool_type") == "invoke_subagent":
                            if session_id in msg.get("result_text", "") or session_id in str(msg.get("args", {})):
                                msg["result_text"] = result or "(no output)"
                                msg["status"] = final_status
                                break
                    self._schedule_session_save(session)
        except Exception as e:
            logger.warning("Subagent tool completion handling failed: %s", e)
