import os
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from core.infrastructure.platform.paths import CONFIG_DIR
from core.infrastructure.platform.platform_utils import cached_json_read
from core.models_catalog import catalog
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen, HeaderWrapOptionList
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_OPTION_LIST,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from widgets.utils.key_aliases import KEY_TOGGLE_DISABLED, expand_bindings
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


class ProvidersScreen(BaseSelectionScreen[Any]):
    """Modal provider selection screen for /providers command with in-place API key step."""

    def __init__(
        self, providers: dict, active_key: str, configured_keys: dict, disabled_providers: list = None, pm=None
    ):
        self.providers = providers
        self.active_key = active_key
        self.configured_keys = configured_keys
        self.disabled_set = set(disabled_providers or [])
        self.pm = pm
        self.step = 1
        self.selected_key: str | None = None
        self.selected_step1_index: int | None = None

        options, items = self._build_options()
        super().__init__(
            title="### **Manage AI Providers**",
            options=options,
            items=items,
            default_value=active_key if active_key in items else (items[0] if items else ""),
            show_search=True,
            search_placeholder="Search...",
            hint_text="enter: connect • space/tab: toggle • esc: close",
            dialog_classes="modal-dialog-medium",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}")
            return option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)
        except Exception:
            return option_list_row_width(None, MODAL_MEDIUM_ROW_WIDTH)

    def _get_provider_model_count(self, key: str, p: dict) -> int:
        models = p.get("models")
        if isinstance(models, list) and models:
            return len(models)
        try:
            cache_path = os.path.join(CONFIG_DIR, "cache", f"models_{key}.json")
            if os.path.exists(cache_path):
                cdata = cached_json_read(cache_path, {})
                if isinstance(cdata, dict):
                    c_models = cdata.get("models", [])
                    if isinstance(c_models, list) and c_models:
                        return len(c_models)
        except Exception:
            pass
        try:
            cat_p = catalog.get_catalog_provider(key)
            if isinstance(cat_p, dict):
                cat_models = cat_p.get("models", [])
                if isinstance(cat_models, list) and cat_models:
                    return len(cat_models)
        except Exception:
            pass
        return 0

    def _build_options(self):
        options = []
        items = []
        target_w = self._row_width()
        for pkey, p in self.providers.items():
            if not isinstance(p, dict):
                continue
            key = p.get("key") or pkey
            name = p.get("name") or pkey
            has_key = bool(self.configured_keys.get(key))
            is_active = key == self.active_key
            is_disabled = key in self.disabled_set or not p.get("enabled", True)

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
                cnt = self._get_provider_model_count(key, p)
                if cnt > 0:
                    badge = f"{cnt} {'model' if cnt == 1 else 'models'}"

            opt_str = format_badge_row(name, badge=badge, prefix=f"{stag} ", target_width=target_w)
            options.append(opt_str)
            items.append(key)
        return options, items

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes=self.dialog_classes or None):
            yield Markdown(self.title, id="providers-markdown", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id=MODAL_SEARCH_INPUT_ID)
            yield HeaderWrapOptionList(*self.filtered_options, id=self.option_list_id)
            yield Markdown("", id="providers-key-current", classes=MODAL_MARKDOWN)
            yield Input(placeholder="API Key...", password=True, id="providers-key-input")
            yield Label(self.hint_text, id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        super().on_mount()
        try:
            self.query_one("#providers-key-current", Markdown).display = False
            self.query_one("#providers-key-input", Input).display = False
        except Exception:
            pass
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


    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("tab", "toggle_disabled", "Toggle Disabled"),
        ("ctrl+t", "toggle_disabled", "Toggle Disabled"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def _show_step_2(self, pkey: str) -> None:
        self.step = 2
        self.selected_key = pkey
        p_info = self.providers.get(pkey, {})
        p_name = (p_info.get("name") or pkey) if isinstance(p_info, dict) else pkey
        curr_key = self.configured_keys.get(pkey) or (self.pm.get_api_key(pkey) if self.pm else "")

        try:
            md = self.query_one("#providers-markdown", Markdown)
            md.update(f"### **Connect {p_name}**")
        except Exception:
            pass

        if self.show_search:
            try:
                self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input).display = False
            except Exception:
                pass

        try:
            self.query_one(f"#{self.option_list_id}", OptionList).display = False
        except Exception:
            pass

        try:
            curr_md = self.query_one("#providers-key-current", Markdown)
            if curr_key:
                if len(curr_key) > 8:
                    masked = f"{curr_key[:4]}...{curr_key[-4:]}"
                else:
                    masked = curr_key
                curr_md.update(f"Current API Key: `{masked}`")
                curr_md.display = True
            else:
                curr_md.display = False
        except Exception:
            pass

        try:
            key_inp = self.query_one("#providers-key-input", Input)
            key_inp.value = ""
            key_inp.display = True
            key_inp.focus()
            try:
                from textual.widgets._input import Selection
                key_inp.selection = Selection(0, 0)
            except Exception:
                pass
            self.clear_selection()
        except Exception:
            pass

        try:
            hint_lbl = self.query_one(f"#{MODAL_HINT_ID}", Label)
            hint_lbl.update("enter: save • esc: back")
        except Exception:
            pass

    def _show_step_1(self) -> None:
        self.step = 1
        self.selected_key = None
        try:
            self.clear_selection()
        except Exception:
            pass

        try:
            md = self.query_one("#providers-markdown", Markdown)
            md.update(self.title)
        except Exception:
            pass

        if self.show_search:
            try:
                self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input).display = True
            except Exception:
                pass

        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            opt_list.display = True
        except Exception:
            pass

        try:
            self.query_one("#providers-key-current", Markdown).display = False
            self.query_one("#providers-key-input", Input).display = False
        except Exception:
            pass

        try:
            hint_lbl = self.query_one(f"#{MODAL_HINT_ID}", Label)
            hint_lbl.update(self.hint_text)
        except Exception:
            pass

        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            if self.selected_step1_index is not None and 0 <= self.selected_step1_index < len(self.filtered_items):
                opt_list.highlighted = self.selected_step1_index
            if self.show_search:
                self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input).focus()
            else:
                opt_list.focus()
        except Exception:
            pass

    def _handle_selection(self, idx: int | None) -> None:
        if idx is None or idx < 0 or idx >= len(self.filtered_items):
            return
        if self.step == 1:
            item = self.filtered_items[idx]
            if item is not None:
                self.selected_step1_index = idx
                self._show_step_2(item)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "providers-key-input":
            event.stop()
            event.prevent_default()
            key_val = event.value.strip()
            self.dismiss((self.selected_key, key_val))
            return

        if self.step == 1 and event.input.id == MODAL_SEARCH_INPUT_ID:
            event.stop()
            event.prevent_default()
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            idx = opt_list.highlighted
            if idx is None and self.filtered_items:
                idx = 0
            self._handle_selection(idx)
            return

        super().on_input_submitted(event)

    def action_cancel(self) -> None:
        if self.step == 2:
            self._show_step_1()
        else:
            self.dismiss(None)

    def action_toggle_disabled(self) -> None:
        if self.step != 1:
            return
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
                        # Disabling the active provider would otherwise leave the
                        # current agent running on a provider that is now OFF.
                        # Recreate it so the app falls back to an enabled provider.
                        if was_active and self.pm.get_active_provider_key() == pkey:
                            app = getattr(self, "app", None)
                            if app is not None:
                                self.pm.recreate_active_agent(app)
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

    def _on_key(self, event: events.Key) -> None:
        if self.step == 2:
            if event.key == "escape":
                self._show_step_1()
                event.prevent_default()
                event.stop()
                return
            if event.key in TAB_KEYS:
                event.prevent_default()
                event.stop()
                return
            super()._on_key(event)
            return

        if event.key in KEY_TOGGLE_DISABLED or event.key in TAB_KEYS:
            self.action_toggle_disabled()
            event.prevent_default()
            event.stop()
            return
        if event.key == "space":
            search_input = self.query_one_optional(f"#{MODAL_SEARCH_INPUT_ID}", Input)
            if not search_input or not search_input.has_focus or not search_input.value:
                self.action_toggle_disabled()
                event.prevent_default()
                event.stop()
                return
        super()._on_key(event)
