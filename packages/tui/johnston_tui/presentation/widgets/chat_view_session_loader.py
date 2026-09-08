"""Session loading, welcome widget management, and message rollback for ChatView."""
import asyncio
import logging
from typing import Any

from johnston_core.domain.policies.messages import is_ui_visible_user_message
from johnston_tui.presentation.widgets.chat_welcome import WelcomeWidget

logger = logging.getLogger(__name__)

__all__ = ["ChatViewSessionLoaderMixin"]


class ChatViewSessionLoaderMixin:
    """Session loading, welcome widget lifecycle, chat clearing, and message rollback."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._is_loading_session: bool = False
        self._has_welcome: bool = False

    async def clear_chat(self) -> None:
        """Clear all messages, pagination buffer, and restore welcome widget."""
        if hasattr(self, "clear_active_hints"):
            self.clear_active_hints(immediate=True)
        self._unloaded_messages = []
        self._is_loading_older = False
        self._is_loading_session = False
        await self.remove_children()
        self.check_welcome()
        self._auto_follow = True

    def on_mount(self) -> None:
        self.check_welcome()

    def clear_welcome(self) -> None:
        welcomes = [c for c in self.children if isinstance(c, WelcomeWidget) and not getattr(c, "_pruning", False)]
        if not welcomes:
            try:
                welcomes = [w for w in self.query(WelcomeWidget) if not getattr(w, "_pruning", False)]
            except Exception:
                welcomes = []
        for w in welcomes:
            try:
                w.remove()
            except Exception:
                pass
        self._has_welcome = False

    def check_welcome(self) -> None:
        if not getattr(self, "show_welcome", True):
            self.clear_welcome()
            return
        welcomes = [c for c in self.children if isinstance(c, WelcomeWidget) and not getattr(c, "_pruning", False)]
        if not welcomes:
            try:
                welcomes = [w for w in self.query(WelcomeWidget) if not getattr(w, "_pruning", False)]
            except Exception:
                welcomes = []
        msg_children = [
            c
            for c in self.children
            if not isinstance(c, WelcomeWidget)
            and not getattr(c, "_pruning", False)
            and not getattr(c, "_closing", False)
        ]
        if not msg_children:
            if not welcomes:
                self.mount(WelcomeWidget())
                self._has_welcome = True
            else:
                self._has_welcome = True
        else:
            for w in welcomes:
                try:
                    w.remove()
                except Exception:
                    pass
            self._has_welcome = False

    async def load_session(
        self,
        session: Any,
        task_manager: Any = None,
        driver: Any = None,
        is_running: bool = False,
    ) -> None:
        """Load and render session message history into this view with pagination.

        Supports both static restoration (main chat) and dynamic streaming driver (subagent screen).
        """
        self.loading = True
        self._is_loading_session = True
        styles = getattr(self, "styles", None)
        if styles is not None:
            try:
                styles.visibility = "hidden"
            except Exception:
                pass
        if hasattr(self, "anchor") and callable(self.anchor):
            try:
                self.anchor(False)
            except Exception:
                pass
        try:
            for child in list(self.children):
                try:
                    child.remove()
                except Exception:
                    pass

            raw_msgs = getattr(session, "messages", []) if session else []
            msg_list = [dict(m) for m in raw_msgs if isinstance(m, dict)]

            has_user_msg = any(
                isinstance(m, dict) and m.get("type") == "user" and is_ui_visible_user_message(m)
                for m in msg_list
            )
            if not has_user_msg and getattr(session, "prompt", None):
                msg_list.insert(0, {"type": "user", "text": session.prompt})

            raw_page_size = getattr(self, "PAGE_SIZE", 50)
            page_size = raw_page_size if isinstance(raw_page_size, int) else 50
            if len(msg_list) > page_size:
                self._unloaded_messages = msg_list[:-page_size]
                msgs_to_render = msg_list[-page_size:]
            else:
                self._unloaded_messages = []
                msgs_to_render = msg_list

            if driver is not None:
                for idx, evt in enumerate(msgs_to_render):
                    is_last_running = is_running and (idx == len(msgs_to_render) - 1)
                    await driver.consume_session_event(
                        evt,
                        animate=is_last_running,
                        is_active=is_last_running,
                    )
                if not is_running and hasattr(driver, "finalize_thinking_stream"):
                    driver.finalize_thinking_stream()
            else:
                from johnston_tui.presentation.widgets.chat_view_restore import resolve_restore_message_item

                fn = resolve_restore_message_item()
                for msg in msgs_to_render:
                    if not isinstance(msg, dict):
                        continue
                    try:
                        await fn(self, msg, task_manager=task_manager)
                        if len(getattr(self, "children", [])) % 5 == 0:
                            await asyncio.sleep(0)
                    except Exception as err:
                        logger.warning("Error restoring UI message item: %s", err)

            if hasattr(self, "check_welcome") and callable(self.check_welcome):
                self.check_welcome()
        finally:
            self._is_loading_session = False
            self.loading = False

        def _scroll() -> None:
            try:
                if hasattr(self, "scroll_end"):
                    self.scroll_end(animate=False)
            finally:
                if styles is not None:
                    try:
                        styles.visibility = "visible"
                    except Exception:
                        pass

        if hasattr(self, "call_after_refresh") and callable(self.call_after_refresh):
            try:
                self.call_after_refresh(_scroll)
            except Exception:
                _scroll()
        else:
            _scroll()

    async def reset_to_messages(self, messages: list[dict] | None, task_manager: Any = None) -> None:
        """Atomically reset mounted widgets and pagination buffer to the given messages."""
        for child in list(self.children):
            child.remove()
        msg_list = list(messages) if messages is not None else []
        page_size = getattr(self, "PAGE_SIZE", 50)
        if len(msg_list) > page_size:
            self._unloaded_messages = msg_list[:-page_size]
            msgs_to_render = msg_list[-page_size:]
        else:
            self._unloaded_messages = []
            msgs_to_render = msg_list

        for msg in msgs_to_render:
            if isinstance(msg, dict):
                await self.restore_message(msg, task_manager=task_manager)
        self._is_loading_older = False
        self._is_loading_session = False
        self.check_welcome()
        self._auto_follow = True
        self.call_after_refresh(lambda: self.scroll_end(animate=False))

    def rollback_to(self, target_index: int) -> None:
        children = [c for c in self.children if not getattr(c, "_pruning", False)]
        start_idx = max(0, target_index + 1)
        for child in children[start_idx:]:
            child.remove()
        self.check_welcome()
        self._auto_follow = True
        self.call_after_refresh(lambda: self.scroll_end(animate=False))
