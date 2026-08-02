from typing import Any, List


class ToolContext:
    """Unified execution context for tools (isolates UI from business logic)"""

    def __init__(self, app: Any = None, is_subagent: bool = False):
        self.app = app
        self.is_subagent = is_subagent or (getattr(app, "is_subagent", False) if app else False)

    def notify(self, message: str) -> None:
        if self.app and hasattr(self.app, "notify"):
            self.app.notify(message)

    def refresh_status(self) -> None:
        if self.app and hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()

    @property
    def background_tasks(self) -> List[Any]:
        if self.app and hasattr(self.app, "background_tasks"):
            return self.app.background_tasks
        return []

    def add_background_task(self, task: Any) -> None:
        if self.app and hasattr(self.app, "background_tasks"):
            self.app.background_tasks.append(task)
        self.refresh_status()


    def create_agent(self) -> Any:
        if self.app and hasattr(self.app, "pm"):
            return self.app.pm.create_active_agent()
        return None

    def trigger_ai_response(self, prompt: str) -> None:
        if self.app:
            if hasattr(self.app, "trigger_ai_response"):
                self.app.trigger_ai_response(prompt, show_in_ui=False)
            elif hasattr(self.app, "generate_ai_response"):
                if getattr(self.app, "is_generating", False) and hasattr(self.app, "message_queue"):
                    self.app.message_queue.append((prompt, False))
                else:
                    self.app.generate_ai_response(prompt, show_in_ui=False)
