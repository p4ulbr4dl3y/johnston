from textual import events
from textual.widgets import Input, OptionList

from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.confirm import ConfirmScreen
from widgets.presentation.screens.constants import (
    MODAL_SEARCH_INPUT,
)
from widgets.presentation.screens.rename_session import RenameSessionScreen
from widgets.presentation.screens.session_conflict import SessionConflictScreen
from widgets.utils.row_format import (
    MODAL_WIDE_ROW_WIDTH,
    format_badge_row,
    format_relative_time,
    option_list_row_width,
)


def _order_sessions_hierarchically(sessions: list[dict]) -> list[dict]:
    session_map = {str(s.get("id")): s for s in sessions}
    children_map: dict[str, list[dict]] = {}
    roots: list[dict] = []

    for s in sessions:
        pid = str(s.get("parent_id") or "")
        if pid and pid in session_map:
            children_map.setdefault(pid, []).append(s)
        else:
            roots.append(s)

    indices = {str(s.get("id")): -i for i, s in enumerate(sessions)}

    def subtree_updated(s: dict, seen: set[str] | None = None) -> tuple:
        sid = str(s.get("id"))
        if seen is None:
            seen = set()
        if sid in seen:
            return (s.get("updated_at") or 0, s.get("created_at") or 0, indices.get(sid, 0))
        seen.add(sid)
        ts = (s.get("updated_at") or 0, s.get("created_at") or 0, indices.get(sid, 0))
        for child in children_map.get(sid, []):
            ts = max(ts, subtree_updated(child, seen))
        return ts

    roots.sort(key=subtree_updated, reverse=True)

    ordered: list[dict] = []
    visited: set[str] = set()

    def dfs(s: dict) -> None:
        sid = str(s.get("id"))
        if sid in visited:
            return
        visited.add(sid)
        ordered.append(s)
        children = children_map.get(sid, [])
        children.sort(key=subtree_updated, reverse=True)
        for child in children:
            dfs(child)

    for root in roots:
        dfs(root)

    for s in sessions:
        if str(s.get("id")) not in visited:
            dfs(s)

    return ordered


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume) with conflict resolution via SessionConflictScreen."""

    def __init__(
        self,
        sessions: list[dict],
        current_session_id: str | None = None,
        initial_selected_id: str | None = None,
    ):
        ordered_sessions = _order_sessions_hierarchically(sessions)
        self.sessions = ordered_sessions
        self.current_session_id = current_session_id
        self.has_active = bool(
            current_session_id and any(str(s.get("id")) == str(current_session_id) for s in ordered_sessions)
        )
        items = [str(s.get("id")) for s in ordered_sessions]

        highlight_target = initial_selected_id or current_session_id
        if highlight_target and str(highlight_target) in items:
            default_val = str(highlight_target)
        else:
            default_val = items[0] if items else ""

        # Pre-format initial options with safe width
        options = self._format_all_options(MODAL_WIDE_ROW_WIDTH)

        super().__init__(
            title="### **Select Session to Resume**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            hint_text="enter: select • ctrl+r: rename • ctrl+d: delete • ↑↓: nav • esc: close",
            dialog_classes="modal-dialog-wide",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        except Exception:
            opt_list = self
        return option_list_row_width(opt_list, MODAL_WIDE_ROW_WIDTH)

    def _format_all_options(self, target_width: int) -> list[str]:
        options = []
        has_indicator = self.has_active or any(s.get("is_locked") for s in self.sessions)
        session_ids = {str(s.get("id")) for s in self.sessions}
        for s in self.sessions:
            sid = str(s.get("id"))
            is_active = self.has_active and sid == str(self.current_session_id)
            is_locked = bool(s.get("is_locked")) and not is_active
            is_fork = bool(s.get("parent_id") and str(s.get("parent_id")) in session_ids)

            if is_active:
                status_pfx = f"{status_tag('ACTIVE')} "
            elif is_locked:
                status_pfx = f"{status_tag('LOCKED')} "
            else:
                status_pfx = "  " if has_indicator else ""

            branch_pfx = "[dim]└─ [/]" if is_fork else ""
            prefix = f"{status_pfx}{branch_pfx}"
            title = str(s.get("title", ""))
            count = s.get("message_count", 0)
            step_str = "step" if count == 1 else "steps"
            badge_parts = [f"{count} {step_str}"]
            time_str = format_relative_time(s.get("updated_at") or s.get("created_at"))
            if time_str:
                badge_parts.append(time_str)
            badge_plain = " • ".join(badge_parts)
            options.append(
                format_badge_row(title, badge_plain, target_width=target_width, prefix=prefix)
            )
        return options

    def _refresh_options(self) -> None:
        target_w = self._row_width()
        self.raw_options = self._format_all_options(target_w)
        self.raw_items = [str(s.get("id")) for s in self.sessions]
        try:
            search_inp = self.query_one(MODAL_SEARCH_INPUT, Input)
            query = search_inp.value
        except Exception:
            query = ""
        self._filter_options(query)
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            if opt_list.highlighted is None and self.filtered_items:
                opt_list.highlighted = 0
        except Exception:
            pass

    def on_mount(self) -> None:
        self._apply_dialog_fit()
        super().on_mount()
        self._refresh_options()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self._refresh_options()

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+r", "f2"):
            self._start_rename_selected()
            event.prevent_default()
            event.stop()
            return
        if event.key in ("ctrl+d", "delete"):
            self._start_delete_selected()
            event.prevent_default()
            event.stop()
            return
        super()._on_key(event)

    def _start_delete_selected(self) -> None:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            idx = opt_list.highlighted
        except Exception:
            idx = None
        if idx is None or idx < 0 or idx >= len(self.filtered_items):
            return
        sid = str(self.filtered_items[idx])
        sess_dict = next((s for s in self.sessions if str(s.get("id")) == sid), None)
        if not sess_dict:
            return

        app = getattr(self, "app", None)
        if self.has_active and sid == str(self.current_session_id):
            if app and hasattr(app, "notify"):
                app.notify("Cannot delete active session", severity="warning")
            return
        if sess_dict.get("is_locked"):
            if app and hasattr(app, "notify"):
                app.notify("Cannot delete locked session", severity="warning")
            return

        title = str(sess_dict.get("title") or sid)

        def on_confirmed(confirmed: bool | None) -> None:
            if confirmed:
                self._apply_delete(sid)
            try:
                if self.show_search:
                    self.query_one(MODAL_SEARCH_INPUT, Input).focus()
                else:
                    self.query_one(f"#{self.option_list_id}", OptionList).focus()
            except Exception:
                pass

        if app:
            app.push_screen(
                ConfirmScreen(
                    title="### **Delete Session**",
                    message=f"Delete **{title}**?\nThis cannot be undone.",
                    confirm_label="delete",
                    cancel_label="cancel",
                ),
                callback=on_confirmed,
            )

    def _apply_delete(self, session_id: str) -> None:
        app = getattr(self, "app", None)
        if app and hasattr(app, "sm"):
            app.sm.delete(session_id)

        self.sessions = [s for s in self.sessions if str(s.get("id")) != str(session_id)]

        if app and hasattr(app, "notify"):
            app.notify("Session deleted", severity="information", timeout=1.5)

        self._refresh_options()

    def _start_rename_selected(self) -> None:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            idx = opt_list.highlighted
        except Exception:
            idx = None
        if idx is None or idx < 0 or idx >= len(self.filtered_items):
            return
        sid = self.filtered_items[idx]
        sess_dict = next((s for s in self.sessions if str(s.get("id")) == str(sid)), None)
        if not sess_dict:
            return
        current_title = str(sess_dict.get("title") or "")
        if current_title == "Untitled":
            current_title = ""

        def on_renamed(new_title: str | None) -> None:
            if new_title is not None:
                clean_title = new_title.strip()
                if clean_title:
                    self._apply_rename(str(sid), clean_title)
            try:
                if self.show_search:
                    self.query_one(MODAL_SEARCH_INPUT, Input).focus()
                else:
                    self.query_one(f"#{self.option_list_id}", OptionList).focus()
            except Exception:
                pass

        if getattr(self, "app", None):
            self.app.push_screen(RenameSessionScreen(current_title=current_title), callback=on_renamed)

    def _apply_rename(self, session_id: str, new_title: str) -> None:
        app = getattr(self, "app", None)
        if app and hasattr(app, "sm"):
            sess = app.sm.get(session_id)
            if not sess and session_id == getattr(app, "current_session_id", None):
                try:
                    role = getattr(app, "role", "worker") or "worker"
                    sess = app.sm.create_main(session_id, role=role)
                except Exception:
                    sess = None
            if sess:
                sess.title = new_title
                if (
                    hasattr(app, "agent")
                    and getattr(app.agent, "history", None)
                    and session_id == getattr(app, "current_session_id", None)
                ):
                    sess.agent_history = list(app.agent.history)
                app.sm.save(sess)

        for s in self.sessions:
            if str(s.get("id")) == str(session_id):
                s["title"] = new_title

        if app:
            if session_id == getattr(app, "current_session_id", None) and hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()
            if hasattr(app, "notify"):
                app.notify("Session renamed", severity="information", timeout=1.5)

        self._refresh_options()

    def _handle_selection(self, idx: int | None) -> None:
        if idx is None or idx < 0 or idx >= len(self.filtered_items):
            return

        sid = str(self.filtered_items[idx])
        sess = next((s for s in self.sessions if str(s.get("id")) == sid), None)
        if sess and sess.get("is_locked"):
            app = getattr(self, "app", None)
            if app:
                def on_conflict_resolved(choice: str | None) -> None:
                    if choice:
                        self.dismiss(f"{choice}:{sid}")
                    else:
                        try:
                            if self.show_search:
                                self.query_one(MODAL_SEARCH_INPUT, Input).focus()
                            else:
                                self.query_one(f"#{self.option_list_id}", OptionList).focus()
                        except Exception:
                            pass

                app.push_screen(
                    SessionConflictScreen(session_id=sid, session_title=str(sess.get("title") or "")),
                    callback=on_conflict_resolved,
                )
            return

        self.dismiss(sid)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        event.prevent_default()
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            idx = opt_list.highlighted
        except Exception:
            idx = 0
        if idx is None and self.filtered_items:
            idx = 0
        self._handle_selection(idx)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        event.prevent_default()
        self._handle_selection(event.option_index)
