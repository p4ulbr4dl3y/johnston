from typing import Any, Dict, List, Optional, Tuple, Union

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList
from textual.widgets.option_list import Option

from core.models_catalog import catalog
from widgets.screens.base_selection import BaseSelectionScreen


class VisionWarningScreen(BaseSelectionScreen[Optional[str]]):
    """Modal screen warning the user when a selected model lacks vision capabilities."""

    def __init__(self, model_name: str, provider_name: str = ""):
        self.model_name = model_name
        self.provider_name = provider_name

        options = ["Select Dedicated Vision Model"]
        items = ["select_vision"]

        fb_prov, fb_model = catalog.get_fallback_vision_model()
        if fb_model:
            fb_disp = catalog.get_model_display_name(fb_prov, fb_model)
            options.append(f"Use Fallback ({fb_disp})")
            items.append("use_fallback")

        options.append("My Model Supports Vision (Force)")
        items.append("force_vision")

        title = (
            "### **Vision Support Warning**\n\n"
            "The selected model does not natively support **Vision**.\n"
            "Image reading will operate in **Agent Fallback Mode**."
        )

        super().__init__(
            title=title,
            options=options,
            items=items,
            default_value="select_vision",
            show_search=False,
        )


class ModelScreen(BaseSelectionScreen[Union[str, Tuple[str, str], None]]):
    """Modal model selection screen (/models)"""

    def __init__(
        self,
        models_data: Union[List[str], Dict[str, Dict[str, Any]]],
        current_model: str = "",
        current_provider: str = "",
        initial_tab: str = "all"
    ):
        self.models_data = models_data
        self.current_model = current_model
        self.current_provider = current_provider
        self.active_tab = initial_tab

        self._tabs_cache: Dict[str, Tuple[Any, Any, Any]] = {
            "all": self._build_data("all"),
            "vision": self._build_data("vision"),
        }
        options, items, default_val = self._tabs_cache[initial_tab]

        super().__init__(
            title=self._get_header_title_text(initial_tab),
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search models..."
        )

    @staticmethod
    def _get_header_title_text(tab: str) -> str:
        if tab == "all":
            return "### **[ All Models ]** &nbsp;&nbsp;&nbsp;&nbsp; Vision Models"
        else:
            return "### &nbsp;&nbsp; All Models &nbsp;&nbsp;&nbsp;&nbsp; **[ Vision Models ]**"

    @staticmethod
    def _is_active_model(p_key: str, m: str, target_prov: str, target_model: str) -> bool:
        if not target_model:
            return False
        if target_prov and p_key and p_key.lower() != target_prov.lower():
            return False

        m_low, t_low = m.lower(), target_model.lower()
        if m_low == t_low:
            return True

        clean_m = catalog.get_model_display_name(p_key, m).lower()
        clean_t = catalog.get_model_display_name(target_prov or p_key, target_model).lower()
        return bool(clean_m and clean_t and clean_m == clean_t)

    def _build_data(self, tab: str) -> Tuple[List[Union[str, Option]], List[Union[str, Tuple[str, str], None]], Union[str, Tuple[str, str], None]]:
        filter_vision = (tab == "vision")
        options: List[Union[str, Option]] = []
        items: List[Union[str, Tuple[str, str], None]] = []
        default_val: Union[str, Tuple[str, str], None] = None

        if filter_vision:
            fb_prov, fb_model = catalog.get_fallback_vision_model()
            if fb_model:
                target_prov, target_model = fb_prov, fb_model
            else:
                target_prov, target_model = self.current_provider, self.current_model
        else:
            target_prov, target_model = self.current_provider, self.current_model

        if isinstance(self.models_data, dict):
            first_group = True
            for p_key, p_info in self.models_data.items():
                p_name = p_info.get("name", p_key)
                p_models = p_info.get("models", [])
                if filter_vision:
                    p_models = [m for m in p_models if catalog.supports_vision(p_key, m)]

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
                    status_tag = r"\[ACTIVE]"
                    opt_label = f"   {status_tag} {clean_m}" if is_active else f"   {clean_m}"
                    item_val = (p_key, m, p_name)
                    options.append(opt_label)
                    items.append(item_val)

                    if is_active:
                        default_val = item_val
        else:
            p_models = self.models_data
            if filter_vision:
                p_models = [m for m in p_models if catalog.supports_vision(self.current_provider, m)]

            active_idx = None
            if target_model:
                for idx, m in enumerate(p_models):
                    if self._is_active_model(self.current_provider, m, target_prov, target_model):
                        active_idx = idx
                        break

            for idx, m in enumerate(p_models):
                clean_m = catalog.get_model_display_name(self.current_provider, m)
                is_active = bool(active_idx is not None and idx == active_idx)
                status_tag = r"\[ACTIVE]"
                opt_label = f"{status_tag} {clean_m}" if is_active else clean_m
                options.append(opt_label)
                items.append(m)
                if is_active:
                    default_val = m

        if default_val is None:
            for it in items:
                if it is not None:
                    default_val = it
                    break

        return options, items, default_val

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self._get_header_title_text(self.active_tab), id="model-title", classes="modal-markdown")
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id="modal-search-input")
            yield OptionList(*self.filtered_options, id="modal-option-list")
            yield Label("←/→: switch tab • enter: select • esc: cancel • ↑/↓: navigate", id="modal-hint")

    def switch_tab(self, new_tab: str) -> None:
        self.active_tab = new_tab
        try:
            title_md = self.query_one("#model-title", Markdown)
            title_md.update(self._get_header_title_text(new_tab))
        except Exception:
            pass

        options, items, default_val = self._tabs_cache.get(new_tab) or self._build_data(new_tab)
        self.raw_options = options
        self.raw_items = items
        self.default_value = default_val

        try:
            search_input = self.query_one("#modal-search-input", Input)
            self.on_input_changed(Input.Changed(search_input, search_input.value))
        except Exception:
            pass

        try:
            opt_list = self.query_one("#modal-option-list", OptionList)
            target_idx = None
            if self.default_value in self.filtered_items:
                target_idx = self.filtered_items.index(self.default_value)
            opt_list.highlighted = target_idx
        except Exception:
            pass

    def _on_key(self, event: events.Key) -> None:
        try:
            search_input = self.query_one("#modal-search-input", Input)
            if search_input.has_focus and event.key in ("left", "right"):
                return
        except Exception:
            pass

        if event.key in ("left", "right", "tab", "backtab", "shift+tab"):
            new_tab = "vision" if self.active_tab == "all" else "all"
            self.switch_tab(new_tab)
            event.prevent_default()
            event.stop()
            return
        super()._on_key(event)

    def dismiss(self, result: Any = None) -> None:
        if result is not None and not (isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], bool)):
            super().dismiss((result, self.active_tab == "vision"))
        else:
            super().dismiss(result)
