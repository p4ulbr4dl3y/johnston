from widgets.patch import apply_textual_patches

apply_textual_patches()

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App

from core.infrastructure.tasks.manager import TaskManager
from core.provider_manager import ProviderManager
from core.session_manager import SessionStore
from widgets.mixins.actions import ActionsMixin
from widgets.mixins.lifecycle import LifecycleMixin
from widgets.mixins.message_flow import MessageFlowMixin
from widgets.mixins.session_persistence import SessionPersistenceMixin
from widgets.utils.key_aliases import expand_bindings

_CSS_PATH = Path(__file__).resolve().parents[2] / "app.tcss"


class JohnstonApp(LifecycleMixin, MessageFlowMixin, SessionPersistenceMixin, ActionsMixin, App):
    """Minimalist Johnston TUI agent with provider/model configuration and isolated project sessions"""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = str(_CSS_PATH)
    BINDINGS = expand_bindings([
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
        ("ctrl+b", "background_all", "Background All"),
        ("ctrl+o", "toggle_expand", "Toggle Expand"),
        ("tab", "toggle_role", "Toggle Role"),
        ("shift+tab", "toggle_mode", "Toggle Mode"),
    ])

    def __init__(self, resume_session_id: str | None = None):
        super().__init__()
        from core.infrastructure.runtime.tool_name import normalize_tool_name
        from core.permission_manager import PermissionManager
        from core.role_registry import RoleRegistry

        PermissionManager.configure_instance(tool_name_normalizer=normalize_tool_name)
        RoleRegistry._instance = RoleRegistry(tool_name_normalizer=normalize_tool_name)

        self.pm = ProviderManager()
        self.sm = SessionStore()
        self.task_manager = TaskManager()
        self._subagent_tools: dict[str, Any] = {}
        # task_id -> shell tool card: completion handle for the message-flow
        # repaint once a background shell task exits (chunks stream via the
        # task's output listeners; this registry is only for the final status).
        self._background_shell_widgets: dict[str, Any] = {}
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

        from core.infrastructure.config.config_helpers import load_sandbox_config

        self.selection_copy_active = False
        self.message_queue = []
        self.is_generating = False
        self.sandbox_enabled = load_sandbox_config()
        self._background_tasks: set[asyncio.Task] = set()

    def create_tracked_task(self, coro) -> asyncio.Task | None:
        """Spawn an asyncio task and keep a strong reference until done."""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
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
        from core.infrastructure.platform.platform_utils import copy_to_os_clipboard_async

        self.create_tracked_task(copy_to_os_clipboard_async(text))
        if notify and hasattr(self, "notify"):
            try:
                self.notify("Copied to clipboard", severity="information", timeout=1.5)
            except Exception:
                pass
