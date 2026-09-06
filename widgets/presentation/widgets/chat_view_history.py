import asyncio
import logging
import re
import sys
from contextlib import nullcontext
from typing import Any

from textual.geometry import Size

from core.domain.policies.messages import is_ui_visible_user_message
from core.infrastructure.config.settings import get_settings
from widgets.presentation.widgets.chat_messages import UserMessage
from widgets.presentation.widgets.chat_welcome import WelcomeWidget

logger = logging.getLogger(__name__)


async def restore_message_item(
    chat_view: Any,
    msg: dict,
    before: Any = None,
    task_manager: Any = None,
) -> Any:
    """Restore a saved transcript event dict into a rendered ChatView widget."""
    if not isinstance(msg, dict):
        return None
    mtype = msg.get("type")
    kw = {"before": before} if before is not None else {}
    if mtype == "user":
        if not is_ui_visible_user_message(msg):
            return None
        text = msg.get("display_text") or msg.get("text", "")
        att_count = msg.get("attachments_count", 0)
        if not att_count and msg.get("attachments"):
            att_count = len(msg.get("attachments"))
        return await chat_view.add_user_message(
            text,
            animate=False,
            attachments_count=att_count,
            **kw,
        )
    elif mtype == "bot":
        text = msg.get("text", "")
        if not text.strip():
            return None
        bm = await chat_view.add_bot_message(animate=False, **kw)
        if hasattr(bm, "set_final_content"):
            await bm.set_final_content(text)
        return bm
    elif mtype == "thinking":
        dur = msg.get("duration", 0.0)
        txt = msg.get("text", "")
        tw = await chat_view.add_thinking_widget(animate=False, **kw)
        if hasattr(tw, "finish_thinking"):
            tw.finish_thinking(dur, txt)
        return tw
    elif mtype == "tool":
        ttype = msg.get("tool_type", "")
        target = msg.get("target", "")
        rtext = msg.get("result_text", "")
        targs = msg.get("args", {})
        status = msg.get("status")
        if not ttype and not target and not targs and status == "cancelled":
            return None
        if status == "running":
            task_id = None
            if "[Background Task ID:" in (rtext or ""):
                bg_m = re.search(r"Background Task ID:\s*([^\s\]]+)", rtext)
                if bg_m:
                    task_id = bg_m.group(1)
            mgr = task_manager
            is_live = bool(task_id and mgr is not None and getattr(mgr, "_tasks", {}).get(task_id) is not None)
            if not is_live:
                status = "done" if rtext else "cancelled"
        sub_id = msg.get("subagent_session_id") or (targs.get("session_id") if isinstance(targs, dict) else None)
        if not sub_id and rtext:
            m = re.search(r"(?:\|\s*id\s+|session[_\s-]?id[:=\s]+)([a-zA-Z0-9_-]+)", rtext, re.IGNORECASE)
            if m:
                sub_id = m.group(1)
        if not sub_id and ttype in ("invoke_subagent", "manage_subagent"):
            title = targs.get("title") or targs.get("prompt")
            if title:
                app = None
                try:
                    app = chat_view.app
                except Exception:
                    pass
                store = getattr(app, "sm", None) if app else None
                if store is None:
                    try:
                        from core.infrastructure.storage.session_store import SessionStore

                        store = SessionStore.get_instance()
                    except Exception:
                        store = None
                if store is not None and hasattr(store, "find_session_by_title_or_id"):
                    try:
                        curr_sid = getattr(app, "current_session_id", None) if app else None
                        found = store.find_session_by_title_or_id(str(title), parent_id=curr_sid)
                        if not found:
                            found = store.find_session_by_title_or_id(str(title))
                        if found and getattr(found, "id", None):
                            sub_id = str(found.id)
                            f_status = getattr(found, "status", None)
                            if status in ("running", "cancelled") and f_status in (
                                "error",
                                "cancelled",
                                "done",
                                "completed",
                            ):
                                status = (
                                    "error"
                                    if f_status == "error"
                                    else ("cancelled" if f_status == "cancelled" else "done")
                                )
                    except Exception:
                        pass
        if sub_id:
            msg["subagent_session_id"] = str(sub_id)

        widget = await chat_view.add_tool_call(
            ttype,
            target,
            result_text=rtext,
            args=targs,
            status=status,
            returncode=msg.get("returncode"),
            animate=False,
            subagent_session_id=sub_id,
            **kw,
        )
        return widget
    elif mtype == "event_divider":
        ctxt = msg.get("text", "Session Compacted")
        return await chat_view.add_event_divider(ctxt, animate=False, **kw)
    elif mtype == "error":
        ctxt = msg.get("text", "")
        return await chat_view.add_error_message(ctxt, animate=False, **kw)
    return None


def _resolve_restore_message_item() -> Any:
    mod = sys.modules.get("widgets.presentation.widgets.chat_container")
    if mod is not None and hasattr(mod, "restore_message_item"):
        return getattr(mod, "restore_message_item")
    return restore_message_item


def _get_settings() -> Any:
    mod = sys.modules.get("widgets.presentation.widgets.chat_container")
    if mod is not None and hasattr(mod, "get_settings"):
        return getattr(mod, "get_settings")()
    return get_settings()


class ChatViewHistoryMixin:
    """Pagination, session loading, welcome widget, and message restoration for ChatView."""

    PAGINATION_THRESHOLD: int = 10

    @property
    def PAGE_SIZE(self) -> int:
        """Messages mounted per page when restoring older sessions (ui.chat_page_size)."""
        if hasattr(self, "_page_size") and self._page_size is not None:
            return self._page_size
        return _get_settings().ui.chat_page_size

    @PAGE_SIZE.setter
    def PAGE_SIZE(self, value: int) -> None:
        self._page_size = value

    def __init__(self, *args: Any, show_welcome: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.show_welcome = show_welcome
        self._is_loading_session = False
        self._unloaded_messages = []
        self._is_loading_older = False
        self._pagination_anchor = None
        self._pagination_anchor_offset = 0
        self._has_welcome = False

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

    def get_total_user_message_count(self) -> int:
        """Return total count of visible user turns (both unloaded and mounted)."""
        unloaded_count = sum(
            1
            for m in self._unloaded_messages
            if isinstance(m, dict) and m.get("type") == "user" and is_ui_visible_user_message(m)
        )
        mounted_count = sum(1 for c in self.children if isinstance(c, UserMessage))
        return unloaded_count + mounted_count

    async def _load_older_messages_worker(self) -> None:
        if self._is_loading_older or not self._unloaded_messages:
            return
        self._is_loading_older = True
        self._auto_follow = False
        new_widgets: list[Any] = []
        try:
            chunk = self._unloaded_messages[-self.PAGE_SIZE :]
            self._unloaded_messages = self._unloaded_messages[: -self.PAGE_SIZE]
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

    async def restore_message(self, msg: dict, before: Any = None, task_manager: Any = None) -> Any:
        """Restore a single message item dict into this view."""
        fn = _resolve_restore_message_item()
        return await fn(self, msg, before=before, task_manager=task_manager)

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
                fn = _resolve_restore_message_item()
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


__all__ = ["ChatViewHistoryMixin", "restore_message_item"]
