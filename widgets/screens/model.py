from typing import Any, Dict, List, Optional, Tuple, Union

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Markdown, OptionList
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
        current_provider: str = "",
        initial_tab: str = "all"
    ):
        self.models_data = models_data
        self.current_model = current_model
        self.current_provider = current_provider
        self.active_tab = initial_tab

        options, items, default_val = self._build_data(initial_tab)

        super().__init__(
            title="### **Select model by provider**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search models..."
        )

    def _build_data(self, tab: str) -> Tuple[List[Union[str, Option]], List[Union[str, Tuple[str, str], None]], Union[str, Tuple[str, str], None]]:
        filter_vision = (tab == "vision")
        options: List[Union[str, Option]] = []
        items: List[Union[str, Tuple[str, str], None]] = []
        default_val: Union[str, Tuple[str, str], None] = None

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

                for m in p_models:
                    clean_m = catalog.get_model_display_name(p_key, m)
                    opt_label = f"   {clean_m}"
                    item_val = (p_key, m, p_name)
                    options.append(opt_label)
                    items.append(item_val)

                    if p_key == self.current_provider and m == self.current_model:
                        default_val = item_val

            valid_items = [it for it in items if it is not None]
            if not default_val and valid_items:
                default_val = valid_items[0]
        else:
            p_models = self.models_data
            if filter_vision:
                p_models = [m for m in p_models if catalog.supports_vision(self.current_provider, m)]
            for m in p_models:
                clean_m = catalog.get_model_display_name(self.current_provider, m)
                options.append(clean_m)
                items.append(m)
            default_val = self.current_model if self.current_model in items else (items[0] if items else "")

        return options, items, default_val

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            with Horizontal(classes="modal-tabs"):
                yield Button(
                    "All Models",
                    id="tab-all",
                    classes="modal-tab active-tab" if self.active_tab == "all" else "modal-tab"
                )
                yield Button(
                    "Vision Models",
                    id="tab-vision",
                    classes="modal-tab active-tab" if self.active_tab == "vision" else "modal-tab"
                )
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id="modal-search-input")
            yield OptionList(*self.filtered_options, id="modal-option-list")
            yield Label("enter: select • tab: switch tab • esc: cancel • ↑/↓: navigate", id="modal-hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("tab-all", "tab-vision"):
            new_tab = "all" if event.button.id == "tab-all" else "vision"
            if new_tab != self.active_tab:
                self.switch_tab(new_tab)

    def switch_tab(self, new_tab: str) -> None:
        self.active_tab = new_tab
        try:
            btn_all = self.query_one("#tab-all", Button)
            btn_vision = self.query_one("#tab-vision", Button)

            if new_tab == "all":
                btn_all.add_class("active-tab")
                btn_vision.remove_class("active-tab")
            else:
                btn_vision.add_class("active-tab")
                btn_all.remove_class("active-tab")
        except Exception:
            pass

        options, items, default_val = self._build_data(new_tab)
        self.raw_options = options
        self.raw_items = items
        self.default_value = default_val

        try:
            search_input = self.query_one("#modal-search-input", Input)
            self.on_input_changed(Input.Changed(search_input, search_input.value))
        except Exception:
            pass

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right"):
            if self.active_tab == "all" and event.key == "right":
                self.switch_tab("vision")
                event.prevent_default()
                event.stop()
                return
            elif self.active_tab == "vision" and event.key == "left":
                self.switch_tab("all")
                event.prevent_default()
                event.stop()
                return
        elif event.key == "tab":
            new_tab = "vision" if self.active_tab == "all" else "all"
            self.switch_tab(new_tab)
            event.prevent_default()
            event.stop()
            return
        super()._on_key(event)
