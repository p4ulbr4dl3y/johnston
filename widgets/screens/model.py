from typing import Any, Dict, List, Optional, Tuple, Union

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown
from textual.widgets.option_list import Option

from core.models_catalog import catalog
from widgets.screens.base_selection import BaseSelectionScreen


class VisionWarningScreen(ModalScreen[Optional[str]]):
    """Modal screen warning the user when a selected model lacks vision capabilities."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(self, model_name: str, provider_name: str = ""):
        super().__init__()
        self.model_name = model_name
        self.provider_name = provider_name

    def compose(self) -> ComposeResult:
        content = (
            "### **Vision Support Warning**\n\n"
            "The selected model does not natively support **Vision**.\n\n"
            "Image reading will operate in **Agent Fallback Mode**."
        )
        with Vertical(id="modal-dialog"):
            yield Markdown(content, classes="modal-markdown")
            with Horizontal(classes="modal-buttons"):
                yield Button("Select Vision Model", id="btn-select-vision")
                yield Button("My Model Supports Vision", id="btn-force-vision")
            yield Label("enter: select • tab / ←/→: switch button • esc: continue", id="modal-hint")

    def on_mount(self) -> None:
        try:
            self.query_one("#btn-select-vision", Button).focus()
        except Exception:
            pass

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right"):
            try:
                btn1 = self.query_one("#btn-select-vision", Button)
                btn2 = self.query_one("#btn-force-vision", Button)
                if btn1.has_focus:
                    btn2.focus()
                    event.prevent_default()
                    event.stop()
                    return
                elif btn2.has_focus:
                    btn1.focus()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass
        super()._on_key(event)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-select-vision":
            self.dismiss("select_vision")
        elif event.button.id == "btn-force-vision":
            self.dismiss("force_vision")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_quit_app(self) -> None:
        self.app.exit()


class ModelScreen(BaseSelectionScreen[Union[str, Tuple[str, str], None]]):
    """Modal model selection screen (/models)"""

    def __init__(
        self,
        models_data: Union[List[str], Dict[str, Dict[str, Any]]],
        current_model: str = "",
        current_provider: str = ""
    ):
        options: List[Union[str, Option]] = []
        items: List[Union[str, Tuple[str, str], None]] = []
        default_val: Union[str, Tuple[str, str], None] = None

        if isinstance(models_data, dict):
            first_group = True
            for p_key, p_info in models_data.items():
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

                for m in p_models:
                    clean_m = catalog.get_model_display_name(p_key, m)
                    opt_label = f"   {clean_m}"
                    item_val = (p_key, m, p_name)
                    options.append(opt_label)
                    items.append(item_val)

                    if p_key == current_provider and m == current_model:
                        default_val = item_val

            valid_items = [it for it in items if it is not None]
            if not default_val and valid_items:
                default_val = valid_items[0]
        else:
            for m in models_data:
                clean_m = catalog.get_model_display_name(current_provider, m)
                options.append(clean_m)
                items.append(m)
            default_val = current_model if current_model in items else (items[0] if items else "")

        super().__init__(
            title="### **Select model by provider**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search models..."
        )
