from typing import Any, Dict, List, Tuple, Union

from widgets.screens.base_selection import BaseSelectionScreen


class ModelScreen(BaseSelectionScreen[Union[str, Tuple[str, str]]]):
    """Modal model selection screen (/models)"""

    def __init__(
        self,
        models_data: Union[List[str], Dict[str, Dict[str, Any]]],
        current_model: str = "",
        current_provider: str = ""
    ):
        options: List[str] = []
        items: List[Union[str, Tuple[str, str]]] = []
        default_val: Union[str, Tuple[str, str]] = ""

        if isinstance(models_data, dict):
            for p_key, p_info in models_data.items():
                p_name = p_info.get("name", p_key)
                for m in p_info.get("models", []):
                    clean_m = m.split("/")[-1] if "/" in m else m
                    opt_label = f"[{p_name}] {clean_m}"
                    item_val = (p_key, m)
                    options.append(opt_label)
                    items.append(item_val)

                    if p_key == current_provider and m == current_model:
                        default_val = item_val

            if not default_val and items:
                default_val = items[0]
        else:
            for m in models_data:
                clean_m = m.split("/")[-1] if "/" in m else m
                options.append(clean_m)
                items.append(m)
            default_val = current_model if current_model in items else (items[0] if items else "")

        super().__init__(
            title="### **Select model by provider (/models)**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True
        )
