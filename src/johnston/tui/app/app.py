from johnston.tui.patch import apply_textual_patches

apply_textual_patches()

import asyncio
from pathlib import Path

from textual.app import App

from johnston.core.infrastructure.platform.logging_setup import adopt_task_exception
from johnston.tui.mixins.actions import ActionsMixin
from johnston.tui.mixins.lifecycle import LifecycleMixin
from johnston.tui.mixins.message_flow import MessageFlowMixin
from johnston.tui.mixins.session_persistence import SessionPersistenceMixin
from johnston.tui.utils.key_aliases import expand_bindings

_CSS_PATH = Path(__file__).resolve().parents[1] / "app.tcss"


class JohnstonApp(LifecycleMixin, MessageFlowMixin, SessionPersistenceMixin, ActionsMixin, App):
    """Minimalist Johnston TUI agent with provider/model configuration and isolated project sessions"""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = str(_CSS_PATH)
    BINDINGS = expand_bindings([
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
        ("ctrl+b", "background_all", "Background All"),
        ("ctrl+o", "toggle_expand", "Toggle Expand"),
        ("ctrl+p", "toggle_plan", "Toggle Plan"),
        ("ctrl+h", "toggle_plan_hidden", "Hide/Show Plan"),
        ("tab", "toggle_role", "Toggle Role"),
        ("shift+tab", "toggle_mode", "Toggle Mode"),
    ])

    def __init__(
        self,
        resume_session_id: str | None = None,
        continue_latest: bool = False,
        initial_prompt: str | None = None,
        model: str | None = None,
        role: str | None = None,
        mode: str | None = None,
        effort: str | None = None,
        sandbox: bool | None = None,
        theme: str | None = None,
    ):
        super().__init__()
        from johnston.core.infrastructure.config.config_helpers import load_sandbox_config
        from johnston.core.infrastructure.runtime.tool_name import normalize_tool_name
        from johnston.tui.app.startup import (
            apply_startup_flags,
            build_agent,
            configure_global_managers,
            register_textual_themes,
            resolve_session_id,
        )

        register_textual_themes(self)
        configure_global_managers(normalize_tool_name)
        build_agent(self)
        resolve_session_id(self, self.sm, resume_session_id, continue_latest)
        self.sandbox_enabled = load_sandbox_config()
        apply_startup_flags(
            self,
            theme=theme,
            model=model,
            effort=effort,
            sandbox=sandbox,
            mode=mode,
            role=role,
            initial_prompt=initial_prompt,
        )

    def create_tracked_task(self, coro) -> asyncio.Task | None:
        """Spawn an asyncio task and keep a strong reference until done."""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            adopt_task_exception(task)
            return task
        except RuntimeError:
            return None

    def copy_to_clipboard(self, text: str, notify: bool = True) -> None:
        """Copy text to both Textual clipboard (OSC 52) and native OS clipboard."""
        if not text:
            return
        try:
            super().copy_to_clipboard(text)
        except Exception:
            pass
        from johnston.core.infrastructure.platform.platform_utils import copy_to_os_clipboard_async

        self.create_tracked_task(copy_to_os_clipboard_async(text))
        if notify and hasattr(self, "notify"):
            try:
                self.notify("Copied to clipboard", severity="information", timeout=1.5)
            except Exception:
                pass

    def set_app_theme(self, theme_name: str, persist: bool = True) -> None:
        """Switch active theme across UI tokens, stylesheets and markdown renderers."""
        from johnston.tui.app.theme_manager import theme_manager

        theme = theme_manager.set_theme(theme_name, persist=persist)
        if hasattr(self, "register_theme"):
            textual_theme = theme_manager.get_textual_theme(theme)
            self.register_theme(textual_theme)
            self.theme = theme.name
            if hasattr(self, "_watch_theme"):
                try:
                    self._watch_theme(theme.name)
                except Exception:
                    pass
            if hasattr(self, "_refresh_truecolor_filter") and hasattr(self, "ansi_theme"):
                try:
                    self._refresh_truecolor_filter(self.ansi_theme)
                except Exception:
                    pass
            if hasattr(self, "_invalidate_css"):
                try:
                    self._invalidate_css()
                except Exception:
                    pass
        if hasattr(self, "refresh_css"):
            self.refresh_css()
        if hasattr(self, "refresh_status_footer"):
            self.refresh_status_footer()

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Return design token defaults for TCSS stylesheet compilation."""
        from johnston.core.domain.defaults.themes import ZINC_DARK

        return dict(ZINC_DARK.tcss_vars)

    def action_quit(self) -> None:
        """Exit application immediately, cancelling in-flight workers."""
        self.is_app_active = False
        for w in getattr(self, "workers", []):
            if getattr(w, "is_running", False):
                w.cancel()
        self.exit()

