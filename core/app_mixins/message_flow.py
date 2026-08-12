import asyncio
import logging
import math
import time

from textual import events, work

from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView
from widgets.commands import handle_slash_command
from widgets.status_footer import StatusFooter

logger = logging.getLogger(__name__)


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

    async def _create_git_checkpoint_async(self, chat_view) -> None:
        try:
            await self.save_current_session_async()
            curr_sid = getattr(self, "current_session_id", None)
            if curr_sid:
                user_msgs = chat_view.get_user_messages()
                msg_idx = len(user_msgs) - 1
                if msg_idx >= 0:
                    proj_path = getattr(self.sm, "project_path", None) if hasattr(self, "sm") else None
                    from core.git_checkpoint import GitCheckpointManager

                    await asyncio.to_thread(
                        GitCheckpointManager.create_checkpoint, curr_sid, msg_idx, project_path=proj_path
                    )
        except Exception as e:
            logger.warning("Git checkpoint creation failed: %s", e)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str, show_in_ui: bool = True, attachments: list = None) -> None:
        """Stream AI response generation with cancellation support via Esc"""
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

        try:

            if show_in_ui:
                await chat_view.add_user_message(user_text, attachments=attachments)

            bot_msg = None

            await self._create_git_checkpoint_async(chat_view)

            full_prompt = user_text
        except asyncio.CancelledError:
            # Cancellation can arrive while the user message / checkpoint work
            # above is awaiting (before the main stream loop). It must not leave
            # is_generating stuck True with a dead generation that never drains
            # the message queue, so run the same cleanup as the finally below.
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
            return
        except Exception as e:
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
                self.notify(f"Generation failed: {e}", severity="error")
            return

        thinking_widget = None
        current_tool_widget = None

        start_time = time.time()
        try:
            try:
                footer = self.query_one("#status-footer", StatusFooter)
                footer.set_generating(True)
            except Exception:
                pass

            async for step in self.agent.stream_steps(full_prompt, attachments=attachments):
                event_type = step[0]
                val1 = step[1] if len(step) > 1 else ""
                val2 = step[2] if len(step) > 2 else ""
                val3 = step[3] if len(step) > 3 else None

                if event_type == "thinking_start":
                    thinking_widget = await chat_view.add_thinking_widget(val1)
                elif event_type == "thinking_delta":
                    if thinking_widget:
                        thinking_widget.update_thinking(val1)
                elif event_type == "thinking_end":
                    if thinking_widget:
                        try:
                            duration = float(val1)
                            if not math.isfinite(duration):
                                duration = 0.0
                        except Exception:
                            duration = 0.0
                        thinking_widget.finish_thinking(duration, val2)
                    thinking_widget = None
                elif event_type == "tool":
                    if bot_msg:
                        if not bot_msg.content.strip():
                            bot_msg.remove()
                        else:
                            await bot_msg.finalize_stream()
                    bot_msg = None
                    targs = val3 if isinstance(val3, dict) else {}
                    current_tool_widget = await chat_view.add_tool_call(val1, val2, args=targs)
                    self.current_tool_widget = current_tool_widget
                elif event_type == "tool_result":
                    if current_tool_widget:
                        current_tool_widget.set_result(val1)
                    try:
                        await self.save_current_session_async()
                    except Exception:
                        pass
                elif event_type == "queued_user_message":
                    q_msg = val1
                    q_atts = val2 if val2 else None
                    q_show = val3 if val3 is not None else True
                    if q_show:
                        await chat_view.add_user_message(q_msg, attachments=q_atts)
                    await self._create_git_checkpoint_async(chat_view)
                elif event_type == "bot_delta":
                    if val1:
                        if bot_msg is None:
                            if not val1.strip():
                                continue
                            bot_msg = await chat_view.add_bot_message()
                        bot_msg.append_stream_content(val1)
                elif event_type == "bot_reset":
                    # A retry is restarting the reply from scratch: drop the partial
                    # text streamed so far so it doesn't duplicate the new attempt.
                    if bot_msg is not None:
                        try:
                            await bot_msg.reset_stream()
                        except Exception:
                            pass
                elif event_type in ("bot_text", "outro"):
                    if val1.strip():
                        if bot_msg is None:
                            bot_msg = await chat_view.add_bot_message()
                        await bot_msg.finalize_stream(val1)
                        bot_msg = None
                    try:
                        await self.save_current_session_async()
                    except Exception:
                        pass
                elif event_type == "event_divider":
                    await chat_view.add_event_divider(val1 or "Session Compacted")
                    self.refresh_status_footer()
                    try:
                        await self.save_current_session_async()
                    except Exception:
                        pass
        except (asyncio.CancelledError, RuntimeError, Exception) as e:
            if thinking_widget:
                try:
                    duration = time.time() - start_time
                    thinking_widget.finish_thinking(duration)
                except Exception:
                    pass
            if bot_msg and bot_msg.content.strip():
                try:
                    await bot_msg.finalize_stream()
                except Exception:
                    pass
            if isinstance(e, (asyncio.CancelledError, RuntimeError)):
                if hasattr(self, "agent") and hasattr(self.agent, "history"):
                    partial = (bot_msg.content if bot_msg else "").strip()
                    if partial:
                        self.agent.history.append({"role": "assistant", "content": partial})
                    self.agent.history.append(
                        {"role": "user", "content": "[System Note: Response interrupted by user]"}
                    )
                    try:
                        from core.token_util import estimate_tokens

                        sys_tok = getattr(self.agent, "_last_sys_tokens", 0)
                        hist_tok = estimate_tokens(self.agent.history)
                        self.agent.last_context_tokens = sys_tok + hist_tok
                        self.refresh_status_footer()
                    except Exception:
                        pass
                try:
                    await chat_view.add_event_divider("Response Interrupted")
                except Exception:
                    pass

            else:
                if getattr(self, "is_app_active", True):
                    try:
                        self.notify(f"Generation failed: {e}", severity="error")
                    except Exception:
                        pass
        finally:
            if bot_msg and not getattr(bot_msg, "content", "").strip():
                try:
                    bot_msg.remove()
                except Exception:
                    pass
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
            # Race guard: if a message was queued after the agent's last step
            # check but before we finished, kick off a fresh generation.
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
