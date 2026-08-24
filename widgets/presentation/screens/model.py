from typing import Any, Dict, List, Tuple, Union

from textual.widgets.option_list import Option

from core.models_catalog import catalog
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ModelScreen(BaseSelectionScreen[Union[str, Tuple[str, str], None]]):
    """Modal model selection screen (/models)"""

    def __init__(
        self,
        models_data: Union[List[str], Dict[str, Dict[str, Any]]],
        current_model: str = "",
        current_provider: str = "",
    ):
        self.models_data = models_data
        self.current_model = current_model
        self.current_provider = current_provider

        options, items, default_val = self._build_data()

        super().__init__(
            title="### **Select Model**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
        )

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

    def _build_data(
        self,
    ) -> Tuple[List[Union[str, Option]], List[Union[str, Tuple[str, str], None]], Union[str, Tuple[str, str], None]]:
        options: List[Union[str, Option]] = []
        items: List[Union[str, Tuple[str, str], None]] = []
        default_val: Union[str, Tuple[str, str], None] = None

        target_prov, target_model = self.current_provider, self.current_model

        if isinstance(self.models_data, dict):
            first_group = True
            for p_key, p_info in self.models_data.items():
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
                    opt_label = f"   {status_tag('ACTIVE')} {clean_m}" if is_active else f"     {clean_m}"
                    item_val = (p_key, m, p_name)
                    options.append(opt_label)
                    items.append(item_val)

                    if is_active:
                        default_val = item_val
        else:
            p_models = self.models_data

            active_idx = None
            if target_model:
                for idx, m in enumerate(p_models):
                    if self._is_active_model(self.current_provider, m, target_prov, target_model):
                        active_idx = idx
                        break

            for idx, m in enumerate(p_models):
                clean_m = catalog.get_model_display_name(self.current_provider, m)
                is_active = bool(active_idx is not None and idx == active_idx)
                opt_label = f" {status_tag('ACTIVE')} {clean_m}" if is_active else f"   {clean_m}"
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
