from typing import Any, List


class ToolContext:
    """Унифицированный контекст исполнения для инструментов (изолирует UI от бизнес-логики)"""

    def __init__(self, app: Any = None):
        self.app = app

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

    def set_agent_mode(self, mode: str) -> None:
        if self.app:
            if hasattr(self.app, "agent") and self.app.agent:
                self.app.agent.mode = mode
            elif hasattr(self.app, "mode"):
                self.app.mode = mode
            self.refresh_status()

    def toggle_agent_mode(self) -> str:
        if self.app:
            curr = "build"
            if hasattr(self.app, "agent") and self.app.agent:
                curr = getattr(self.app.agent, "mode", "build")
            elif hasattr(self.app, "mode"):
                curr = getattr(self.app, "mode", "build")
            new_mode = "plan" if curr == "build" else "build"
            self.set_agent_mode(new_mode)
            return new_mode
        return "build"

    def create_agent(self) -> Any:
        if self.app and hasattr(self.app, "pm"):
            return self.app.pm.create_active_agent()
        return None

    def trigger_ai_response(self, prompt: str) -> None:
        if self.app and hasattr(self.app, "generate_ai_response"):
            self.app.generate_ai_response(prompt, show_in_ui=False)
