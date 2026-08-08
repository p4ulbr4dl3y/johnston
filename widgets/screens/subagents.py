from widgets.screens.tasks import TasksListScreen


class SubagentsScreen(TasksListScreen):
    """Subclass of TasksListScreen defaulting to Agents tab for backward compatibility."""

    def __init__(self, default_tab: int = 1):
        super().__init__(default_tab=default_tab)
        self.sessions = []
        self.filtered_sessions = []
