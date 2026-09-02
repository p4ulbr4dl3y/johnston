from typing import Any, Dict, List, Optional, Tuple, Union

from textual import events
from textual.widgets import Input
from textual.widgets.option_list import Option

from core.models_catalog import catalog
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import MODAL_SEARCH_INPUT_ID
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


class ModelScreen(BaseSelectionScreen[Union[Tuple[str, str, str], Tuple[str, str], None]]):
    """Modal model selection screen (/models)"""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("ctrl+r", "refresh_models", "Refresh"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(
        self,
        models_data: Dict[str, Dict[str, Any]],
        current_model: str = "",
        current_provider: str = "",
        pm: Optional[Any] = None,
    ):
        self.pm = pm
        self.models_data = models_data
        self.current_model = current_model
        self.current_provider = current_provider
        self._last_built_width = self._row_width()

        options, items, default_val = self._build_data()

        super().__init__(
            title="### **Select Model**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            hint_text="enter Select • ctrl+r Refresh • esc Close",
            dialog_classes="modal-dialog-medium",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}")
            return option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)
        except Exception:
            return option_list_row_width(None, MODAL_MEDIUM_ROW_WIDTH)

    def on_mount(self) -> None:
        super().on_mount()
        curr_w = self._row_width()
        search_val = ""
        if self.show_search:
            try:
                search_input = self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
                search_val = search_input.value
            except Exception:
                pass
        if curr_w != self._last_built_width or search_val:
            self._last_built_width = curr_w
            self.raw_options, self.raw_items, self.default_value = self._build_data()
            self._filter_options(search_val)

    def on_resize(self, event: events.Resize) -> None:
        super().on_resize(event)
        curr_w = self._row_width()
        search_val = ""
        if self.show_search:
            try:
                search_input = self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
                search_val = search_input.value
            except Exception:
                pass
        if curr_w != self._last_built_width or search_val:
            self._last_built_width = curr_w
            self.raw_options, self.raw_items, self.default_value = self._build_data()
            self._filter_options(search_val)

    async def action_refresh_models(self) -> None:
        """Fetch fresh model catalog with force_refresh=True and re-render."""
        pm = self.pm
        if pm is None:
            try:
                pm = getattr(self.app, "pm", None)
            except Exception:
                pm = getattr(self, "_app", None)
                if pm is not None:
                    pm = getattr(pm, "pm", None)

        if not pm:
            self.notify("Provider manager not available", severity="warning")
            return

        try:
            new_data = await pm.fetch_models_grouped(force_refresh=True)
            if new_data:
                self.models_data = new_data
                self.raw_options, self.raw_items, self.default_value = self._build_data()
                self._norm_targets.clear()

                search_val = ""
                if self.show_search:
                    try:
                        search_input = self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
                        search_val = search_input.value
                    except Exception:
                        pass
                self._filter_options(search_val)
                self.notify("Models refreshed")
            else:
                self.notify("No models found", severity="warning")
        except Exception as e:
            self.notify(f"Failed to refresh models: {e}", severity="error")

    @staticmethod
    def _is_active_model(provider_key: str, model_name: str, target_provider: str, target_model: str) -> bool:
        if not target_model:
            return False
        if target_provider and provider_key != target_provider:
            return False
        if model_name == target_model:
            return True
        clean_target = catalog.get_model_display_name(provider_key, target_model)
        clean_model = catalog.get_model_display_name(provider_key, model_name)
        if clean_model and clean_target and clean_model == clean_target:
            return True
        return False

    def _build_data(
        self,
    ) -> Tuple[List[Union[str, Option]], List[Union[Tuple[str, str, str], None]], Union[Tuple[str, str, str], None]]:
        options: List[Union[str, Option]] = []
        items: List[Union[Tuple[str, str, str], None]] = []
        default_val: Union[Tuple[str, str, str], None] = None

        target_prov, target_model = self.current_provider, self.current_model
        target_w = self._row_width()

        first_group = True
        for p_key, p_info in (self.models_data or {}).items():
            p_name = p_info.get("name", p_key)
            p_models = p_info.get("models", [])

            if not p_models:
                continue

            if not first_group:
                options.append(Option("", disabled=True))
                items.append(None)
            first_group = False

            options.append(Option(p_name, disabled=True))
            items.append(None)

            active_idx = None
            if target_model:
                for idx, m in enumerate(p_models):
                    if self._is_active_model(p_key, m, target_prov, target_model):
                        active_idx = idx
                        break

            for idx, m in enumerate(p_models):
                clean_m = catalog.get_model_display_name(p_key, m)
                is_active = bool(active_idx is not None and idx == active_idx)
                has_vis = catalog.has_vision(p_key, m)
                badge = "vision" if has_vis else ""
                prefix = f"{status_tag('ACTIVE')} " if is_active else "  "
                opt_label = format_badge_row(clean_m, badge=badge, target_width=target_w, prefix=prefix)
                item_val = (p_key, m, p_name)
                options.append(opt_label)
                items.append(item_val)

                if is_active:
                    default_val = item_val

        if default_val is None:
            for it in items:
                if it is not None:
                    default_val = it
                    break

        return options, items, default_val
