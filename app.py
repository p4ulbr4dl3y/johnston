import os

from textual.app import App

from widgets.patch import apply_textual_patches

apply_textual_patches()


import logging

logger = logging.getLogger("johnston.app")

from cli import (
    get_version,
    main,
    print_mcp,
    print_models,
    print_rules,
    print_skills,
    print_subagents,
    run_headless_prompt,
)

__all__ = [
    "JohnstonApp",
    "main",
    "get_version",
    "print_models",
    "print_skills",
    "print_mcp",
    "print_rules",
    "print_subagents",
    "run_headless_prompt",
]
from core.app_mixins.actions import ActionsMixin
from core.app_mixins.lifecycle import LifecycleMixin
from core.app_mixins.message_flow import MessageFlowMixin
from core.app_mixins.session_persistence import SessionPersistenceMixin
from core.commands import handle_slash_command  # noqa: F401  (re-exported for tests patching app.handle_slash_command)
from core.provider_manager import ProviderManager
from core.session_manager import SessionStore


class JohnstonApp(LifecycleMixin, MessageFlowMixin, SessionPersistenceMixin, ActionsMixin, App):
    """Minimalist Johnston TUI agent with provider/model configuration and isolated project sessions"""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
        ("ctrl+b", "background_all", "Background All"),
        ("ctrl+o", "toggle_expand", "Toggle Expand"),
        ("shift+tab", "toggle_mode", "Toggle Mode"),
        ("backtab", "toggle_mode", "Toggle Mode"),
    ]

    def __init__(
        self,
        mode: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        resume_session_id: str | None = None,
    ):
        super().__init__()
        self._disable_tooltips = True
        self.pm = ProviderManager()
        if provider:
            self.pm.set_active_provider_key(provider)
        self.sm = SessionStore()
        self.agent = self.pm.create_active_agent()
        if model and self.agent:
            self.agent.model = model
        if mode and self.agent:
            self.agent.mode = mode
        self.mode = getattr(self.agent, "mode", mode or "act") if self.agent else (mode or "act")
        if self.agent:
            self.agent.app = self

        self.resume_session_id = resume_session_id
        if resume_session_id:
            sess = self.sm.get(resume_session_id)
            if sess:
                self.current_session_id = resume_session_id
            else:
                self.current_session_id = self.sm.generate_session_id()
        else:
            self.current_session_id = self.sm.generate_session_id()

        self.selection_copy_active = False
        self.background_tasks = []
        self.message_queue = []
        self.is_generating = False

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to both Textual clipboard (OSC 52) and native OS clipboard."""
        try:
            super().copy_to_clipboard(text)
        except Exception:
            pass
        from core.platform_utils import copy_to_os_clipboard
        copy_to_os_clipboard(text)


if __name__ == "__main__":
    main()
