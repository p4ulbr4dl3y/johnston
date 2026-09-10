from typing import Any

from textual import events
from textual.widgets import Input, OptionList

from johnston.core.dto import ProviderDTO
from johnston.tui.adapters.core_bridge import JohnstonClient
from johnston.tui.presentation.screens.api_key import ApiKeyScreen
from johnston.tui.presentation.screens.base_modal import status_tag
from johnston.tui.presentation.screens.base_selection import BaseSelectionScreen
from johnston.tui.presentation.screens.constants import (
    MODAL_OPTION_LIST,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from johnston.tui.utils.key_aliases import KEY_TOGGLE_DISABLED, expand_bindings
from johnston.tui.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


class ProvidersScreen(BaseSelectionScreen[Any]):
    """Modal provider selection screen for /providers command with separate ApiKeyScreen modal."""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("tab", "toggle_disabled", "Toggle Disabled"),
        ("ctrl+t", "toggle_disabled", "Toggle Disabled"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(
        self,
        providers: list[ProviderDTO],
        active_key: str,
        configured_keys: dict,
        disabled_providers: list = None,
        pm=None,
    ):
        self.providers = providers
        self.active_key = active_key
        self.configured_keys = configured_keys
        self.disabled_set = set(disabled_providers or [])
        self.pm = pm

        options, items = self._build_options()
        super().__init__(
            title="### **Manage AI Providers**",
            options=options,
            items=items,
            default_value=active_key if active_key in items else (items[0] if items else ""),
            show_search=True,
            search_placeholder="Search...",
            hint_text="enter Connect • tab Toggle • esc Close",
            dialog_classes="modal-dialog-medium",
        )

    def _get_client(self):
        """Resolve the active JohnstonClient facade from the host app (test/test-pilot resilience)."""
        try:
            app = self.app
            if hasattr(app, "client") and app.client is not None:
                return app.client
        except Exception:
            pass
        return JohnstonClient()

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}")
            return option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)
        except Exception:
            return option_list_row_width(None, MODAL_MEDIUM_ROW_WIDTH)

    def _build_options(self):
        options = []
        items = []
        target_w = self._row_width()

        for p in self.providers:
            if not isinstance(p, ProviderDTO):
                continue
            key = p.key or p.name
            name = p.name or key
            is_disabled = p.is_disabled or key in self.disabled_set
            has_key = p.is_configured or bool(self.configured_keys.get(key))
            cnt = len(p.models)

            is_active = key == self.active_key

            if is_disabled:
                stag = status_tag("OFF")
            elif is_active:
                stag = status_tag("ACTIVE")
            elif has_key:
                stag = status_tag("ON")
            else:
                stag = status_tag("AUTH")

            badge = ""
            if not is_disabled and (is_active or has_key):
                if cnt > 0:
                    badge = f"{cnt} {'model' if cnt == 1 else 'models'}"

            opt_str = format_badge_row(name, badge=badge, prefix=f"{stag} ", target_width=target_w)
            options.append(opt_str)
            items.append(key)
        return options, items

    def on_mount(self) -> None:
        super().on_mount()
        self.raw_options, self.raw_items = self._build_options()
        search_val = ""
        if self.show_search:
            try:
                search_input = self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
                search_val = search_input.value
            except Exception:
                pass
        self._filter_options(search_val)

    def on_resize(self, event: events.Resize) -> None:
        super().on_resize(event)
        self.raw_options, self.raw_items = self._build_options()
        search_val = ""
        if self.show_search:
            try:
                search_input = self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
                search_val = search_input.value
            except Exception:
                pass
        self._filter_options(search_val)

    def _handle_selection(self, idx: int | None) -> None:
        if idx is None or idx < 0 or idx >= len(self.filtered_items):
            return
        item = self.filtered_items[idx]
        if item is None:
            return

        prov = next((p for p in self.providers if (p.key or p.name) == item), None)
        p_name = prov.name if prov is not None else item
        curr_key = self.configured_keys.get(item) or (self.pm.get_api_key(item) if self.pm else "")

        try:
            app = self.app
        except Exception:
            app = getattr(self, "_app", None)

        if app:
            def on_key_entered(entered_key: str | None) -> None:
                if entered_key is not None:
                    self.dismiss((item, entered_key))
                else:
                    try:
                        if self.show_search:
                            self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input).focus()
                        else:
                            self.query_one(f"#{self.option_list_id}", OptionList).focus()
                    except Exception:
                        pass

            app.push_screen(
                ApiKeyScreen(provider_name=p_name, current_key=curr_key, provider_key=item),
                callback=on_key_entered,
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_toggle_disabled(self) -> None:
        opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        idx = opt_list.highlighted
        if idx is None and self.filtered_items:
            idx = 0
        if idx is not None and 0 <= idx < len(self.filtered_items):
            pkey = self.filtered_items[idx]
            if pkey:
                was_active = bool(self.pm) and pkey == self.pm.get_active_provider_key()
                if pkey in self.disabled_set:
                    self.disabled_set.remove(pkey)
                    if self.pm:
                        self.pm.set_provider_disabled(pkey, False)
                else:
                    self.disabled_set.add(pkey)
                    if self.pm:
                        self.pm.set_provider_disabled(pkey, True)
                        if was_active and self.pm.get_active_provider_key() == pkey:
                            app = getattr(self, "app", None)
                            if app is not None:
                                from johnston.tui.app.role_service import reconcile_active_agent

                                reconcile_active_agent(app)
                                self.active_key = self.pm.get_active_provider_key()

                options, items = self._build_options()
                self.raw_options = options
                self.raw_items = items
                if pkey in items:
                    raw_idx = items.index(pkey)
                    new_label = options[raw_idx]
                    if idx < len(self.filtered_options):
                        self.filtered_options[idx] = new_label
                    try:
                        opt_list.replace_option_prompt_at_index(idx, new_label)
                    except Exception:
                        pass

    async def _on_key(self, event: events.Key) -> None:
        if event.key in KEY_TOGGLE_DISABLED or event.key in TAB_KEYS:
            self.action_toggle_disabled()
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)
