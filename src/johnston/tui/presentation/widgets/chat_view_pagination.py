"""Pagination mixin for ChatView: scroll-compensated loading of older messages."""
import asyncio
import logging
from contextlib import nullcontext
from typing import Any

from textual.geometry import Size

from johnston.tui.presentation.widgets.chat_welcome import WelcomeWidget

logger = logging.getLogger(__name__)

__all__ = ["ChatViewPaginationMixin"]


class ChatViewPaginationMixin:
    """Provides paginated loading of older session messages with scroll compensation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._unloaded_messages: list[dict] = []
        self._is_loading_older: bool = False
        self._pagination_anchor: Any = None
        self._pagination_anchor_offset: int = 0

    def arrange(self, size: Size) -> Any:
        result = super().arrange(size)
        if self._pagination_anchor is not None:
            try:
                for p in result.placements:
                    if p.widget == self._pagination_anchor:
                        target_y = max(0, p.region.y - self._pagination_anchor_offset)
                        self.scroll_y = target_y
                        self.scroll_target_y = target_y
                        break
            except Exception:
                pass
        return result

    def _scroll_update(self, virtual_size: Size) -> None:
        if self._pagination_anchor is not None:
            try:
                v_region = getattr(self._pagination_anchor, "virtual_region", None)
                if v_region is not None and v_region.y >= 0:
                    target_y = max(0, v_region.y - self._pagination_anchor_offset)
                    self.scroll_y = target_y
                    self.scroll_target_y = target_y
            except Exception:
                pass
        super()._scroll_update(virtual_size)

    def remove_children(self, *args: Any, **kwargs: Any) -> Any:
        selector = args[0] if args else kwargs.get("selector", "*")
        if selector == "*" or not selector:
            self._unloaded_messages = []
            self._is_loading_older = False
            self._pagination_anchor = None
        return super().remove_children(*args, **kwargs)

    def has_older_messages(self) -> bool:
        """True if there are older session messages that haven't been mounted yet."""
        return bool(self._unloaded_messages)

    def load_older_messages(self) -> None:
        """Trigger loading and mounting the next batch of older messages."""
        if self._is_loading_older or not self._unloaded_messages:
            return
        if hasattr(self, "run_worker") and callable(self.run_worker):
            try:
                self.run_worker(self._load_older_messages_worker(), exclusive=True)
                return
            except Exception:
                pass
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._load_older_messages_worker())
        except RuntimeError:
            pass

    async def load_all_older_messages(self) -> None:
        """Load and mount all remaining older messages into view."""
        was_bottom = self.is_at_bottom() if hasattr(self, "is_at_bottom") else False
        while self.has_older_messages():
            await self._load_older_messages_worker()
        if was_bottom and hasattr(self, "scroll_to_bottom"):
            self.scroll_to_bottom()

    async def _load_older_messages_worker(self) -> None:
        if self._is_loading_older or not self._unloaded_messages:
            return
        self._is_loading_older = True
        self._auto_follow = False
        new_widgets: list[Any] = []
        try:
            from johnston.tui.presentation.widgets.chat_view_restore import resolve_settings

            page_size = getattr(self, "PAGE_SIZE", None)
            if page_size is None:
                page_size = resolve_settings().ui.chat_page_size
            chunk = self._unloaded_messages[-page_size:]
            self._unloaded_messages = self._unloaded_messages[:-page_size]
            anchor = next((c for c in self.children if not isinstance(c, WelcomeWidget)), None)
            task_mgr = getattr(getattr(self, "app", None), "task_manager", None)
            old_max_y = self.max_scroll_y
            old_scroll_y = self.scroll_y

            if anchor is None:
                for msg in chunk:
                    await self.restore_message(msg, task_manager=task_mgr)
            else:
                anchor_vy = getattr(getattr(anchor, "virtual_region", None), "y", 0)
                self._pagination_anchor = anchor
                self._pagination_anchor_offset = anchor_vy - int(self.scroll_y)

                for msg in chunk:
                    w = await self.restore_message(msg, before=anchor, task_manager=task_mgr)
                    if w is not None:
                        new_widgets.append(w)

                app = getattr(self, "app", None)
                batch_ctx = (
                    app.batch_update() if (app is not None and hasattr(app, "batch_update")) else nullcontext()
                )
                with batch_ctx:
                    for w in new_widgets:
                        try:
                            w.styles.display = "block"
                        except Exception:
                            pass

                def _compensate_scroll() -> None:
                    if self._pagination_anchor is not None:
                        try:
                            v_region = getattr(self._pagination_anchor, "virtual_region", None)
                            if v_region is not None:
                                target_y = max(0, v_region.y - self._pagination_anchor_offset)
                            else:
                                delta = max(0, self.max_scroll_y - old_max_y)
                                target_y = old_scroll_y + delta
                            self.scroll_to(y=target_y, animate=False, immediate=True)
                        except Exception:
                            pass
                        self._pagination_anchor = None
                    elif self.max_scroll_y != old_max_y:
                        try:
                            delta = max(0, self.max_scroll_y - old_max_y)
                            target_y = old_scroll_y + delta
                            self.scroll_to(y=target_y, animate=False, immediate=True)
                        except Exception:
                            pass

                if hasattr(self, "call_after_refresh"):
                    self.call_after_refresh(_compensate_scroll)
                else:
                    _compensate_scroll()
        except Exception as e:
            logger.warning("Failed loading older chat messages: %s", e)
            for w in new_widgets:
                try:
                    w.styles.display = "block"
                except Exception:
                    pass
            self._pagination_anchor = None
        finally:
            self._is_loading_older = False

    def get_total_user_message_count(self) -> int:
        """Return total count of visible user turns (both unloaded and mounted)."""
        from johnston.core.domain.policies.messages import is_ui_visible_user_message
        from johnston.tui.presentation.widgets.chat_messages import UserMessage

        unloaded_count = sum(
            1
            for m in self._unloaded_messages
            if isinstance(m, dict) and m.get("type") == "user" and is_ui_visible_user_message(m)
        )
        mounted_count = sum(1 for c in self.children if isinstance(c, UserMessage))
        return unloaded_count + mounted_count
