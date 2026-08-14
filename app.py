import os

from textual.app import App

from widgets.patch import apply_textual_patches

apply_textual_patches()

from core.infrastructure.tasks.manager import TaskManager
from core.provider_manager import ProviderManager
from core.session_manager import SessionStore
from widgets.mixins.actions import ActionsMixin
from widgets.mixins.lifecycle import LifecycleMixin
from widgets.mixins.message_flow import MessageFlowMixin
from widgets.mixins.session_persistence import SessionPersistenceMixin


class JohnstonApp(LifecycleMixin, MessageFlowMixin, SessionPersistenceMixin, ActionsMixin, App):
    """Minimalist Johnston TUI agent with provider/model configuration and isolated project sessions"""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
        ("ctrl+b", "background_all", "Background All"),
        ("ctrl+o", "toggle_expand", "Toggle Expand"),
        ("shift+tab", "toggle_role", "Toggle Role"),
        ("backtab", "toggle_role", "Toggle Role"),
    ]

    def __init__(self, resume_session_id: str | None = None):
        super().__init__()
        self.pm = ProviderManager()
        self.sm = SessionStore()
        self.task_manager = TaskManager(self)
        self.agent = self.pm.create_active_agent()
        self.role = getattr(self.agent, "role", "worker") if self.agent else "worker"
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
    from cli import main

    main()
