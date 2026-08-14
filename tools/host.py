from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolHost(Protocol):
    """Port (abstraction interface) for the UI host that tools call into.

    Tools never reach for a concrete Textual ``JohnstonApp``; they delegate to
    ``ToolContext`` helpers, which call these methods on a ``ToolHost`` when the
    host supplies them and degrade gracefully otherwise. Every method is
    optional so a minimal/headless host is still a valid tool host.
    """

    def ask_user(self, questions: list[dict]) -> Any:
        """Ask the user a set of questions (async-capable; returns str or coroutine)."""
        return ""

    def confirm_permission(
        self,
        screen_name: str,
        args: Any,
        reason: str,
        perm_name: str = None,
    ) -> bool:
        """Prompt the user to confirm a potentially destructive/powerful action."""
        return True

    def notify(self, message: str, severity: str = "info") -> None:
        """Show a toast/inline notification to the user."""
        return None

    def trigger_ai_response(self, prompt: str) -> None:
        """Feed a prompt back into the AI as if the user typed it."""
        return None

    def refresh_status_footer(self) -> None:
        """Refresh the UI status footer (tokens/cost/tasks)."""
        return None

    def get_task_manager(self) -> Any | None:
        return None

    def get_provider_manager(self) -> Any | None:
        return None

    def get_current_session_id(self) -> str | None:
        return None

    def get_project_dir(self) -> str | None:
        return None
