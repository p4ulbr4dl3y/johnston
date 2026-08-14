import asyncio
import logging

from textual import events, work

from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.commands import handle_slash_command
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
            except Exception:
                pass

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
        from core.ai_generator import GenCanvas
        from core.ai_generator import generate_ai_response as _engine

        # ---- connectivity check (mixin-level) ----
        act_k = self.pm.get_active_provider_key() if hasattr(self, "pm") else ""
        is_connected = self.pm.is_provider_connected(act_k) if (hasattr(self, "pm") and act_k) else False
        if not is_connected or not getattr(self.agent, "model", ""):
            if not is_connected:
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

        canvas = GenCanvas(
            add_user_message=lambda text, atts: chat_view.add_user_message(text, attachments=atts),
            add_thinking_widget=chat_view.add_thinking_widget,
            add_tool_call=lambda name, desc, args: chat_view.add_tool_call(name, desc, args=args),
            register_tool_widget=_register_tool_widget(self),
            add_bot_message=chat_view.add_bot_message,
            add_event_divider=chat_view.add_event_divider,
            get_user_messages=chat_view.get_user_messages,
            refresh_status_footer=self.refresh_status_footer,
            notify=self.notify,
            save_session=lambda: self.save_current_session_async(),
        )

        # ---- pre-stream footer & CancelledError guard ----
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            footer.set_generating(True)
        except Exception:
            pass

        try:
            await _engine(
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
        except Exception:
            # The engine already called canvas.notify for generic exceptions.
            pass
        finally:
            try:
                footer = self.query_one("#status-footer", StatusFooter)
                footer.set_generating(False)
            except Exception:
                pass
            try:
                if getattr(self, "is_app_active", True):
                    await self.save_current_session_async(force=True)
            except Exception:
                pass
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
        """Callback when background shell command finishes"""
        if not getattr(self, "is_app_active", True):
            return
        try:
            from tools.base import format_background_notification

            msg = format_background_notification("Background shell", command_str, task_id, result)
            curr_sid = getattr(self, "current_session_id", None)
            if self.is_generating:
                self.message_queue.append((msg, False, None, curr_sid))
            else:
                self.generate_ai_response(msg, show_in_ui=False)
        except Exception:
            pass
