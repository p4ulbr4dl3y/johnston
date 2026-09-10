from typing import Any, Dict, List, Optional, Tuple, Union

from textual import events
from textual.widgets import Input
from textual.widgets.option_list import Option

from johnston.core.dto import ModelInfoDTO
from johnston.tui.presentation.screens.base_modal import status_tag
from johnston.tui.presentation.screens.base_selection import BaseSelectionScreen
from johnston.tui.presentation.screens.constants import MODAL_SEARCH_INPUT_ID
from johnston.tui.utils.key_aliases import expand_bindings
from johnston.tui.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


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
        client: Optional[Any] = None,
    ):
        self.pm = pm
        if client is None:
            try:
                from johnston.tui.adapters import core_bridge

                client = core_bridge.JohnstonClient(pm=pm)
            except Exception:
                client = None
        self.client = client
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

    def _resolve_model_info(self, provider_key: str, model: Union[str, ModelInfoDTO]) -> ModelInfoDTO:
        if isinstance(model, ModelInfoDTO):
            return model
        m_name = str(model)
        client = self.client or getattr(getattr(self, "app", None), "client", None)
        if client and hasattr(client, "get_model_info"):
            try:
                return client.get_model_info(provider_key, m_name)
            except Exception:
                pass
        return ModelInfoDTO(name=m_name, display_name=m_name, provider=provider_key)

    @staticmethod
    def _is_active_model(
        provider_key: str,
        model: Union[str, ModelInfoDTO],
        target_provider: str,
        target_model: str,
        client: Optional[Any] = None,
    ) -> bool:
        if not target_model:
            return False
        if target_provider and provider_key != target_provider:
            return False
        m_name = model.name if isinstance(model, ModelInfoDTO) else str(model)
        if m_name == target_model:
            return True
        if isinstance(model, ModelInfoDTO):
            clean_display = model.display_name
            if clean_display and (clean_display == target_model or clean_display.lower() == target_model.lower()):
                return True
        if client and hasattr(client, "get_model_info"):
            try:
                info = client.get_model_info(provider_key, m_name)
                clean_display = info.display_name
                clean_target = client.get_model_info(provider_key, target_model).display_name
                if (clean_display and clean_display == target_model) or (
                    clean_display and clean_target and clean_display == clean_target
                ):
                    return True
            except Exception:
                pass
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
                    if self._is_active_model(p_key, m, target_prov, target_model, client=self.client):
                        active_idx = idx
                        break

            for idx, m in enumerate(p_models):
                m_info = self._resolve_model_info(p_key, m)
                m_name = m_info.name
                clean_m = m_info.display_name or m_info.name
                has_vis = m_info.supports_vision
                has_thinking = m_info.supports_thinking

                is_active = bool(active_idx is not None and idx == active_idx)
                badges = []
                if has_vis:
                    badges.append("vision")
                if has_thinking:
                    badges.append("thinking")
                badge = ", ".join(badges) if badges else ""
                prefix = f"{status_tag('ACTIVE')} " if is_active else "  "
                opt_label = format_badge_row(clean_m, badge=badge, target_width=target_w, prefix=prefix)
                item_val = (p_key, m_name, p_name)
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
