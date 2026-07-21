from textual.widgets import OptionList
from commands import COMMAND_REGISTRY

COMMANDS = [(name, cmd.description) for name, cmd in COMMAND_REGISTRY.items()]

class CommandSuggestions(OptionList):
    """Выпадающее меню подсказок слэш-команд (/help, /rewind)"""
    
    can_focus = False
    ALLOW_SELECT = False

    def update_query(self, text: str) -> list[str]:
        """Обновление списка совпадений с форматированием в две колонки"""
        self.clear_options()
        
        cleaned = text.strip().lower()
        if not cleaned.startswith("/") or " " in cleaned:
            self.display = False
            return []

        matched_cmds = []
        for cmd, desc in COMMANDS:
            if cmd.startswith(cleaned):
                matched_cmds.append(cmd)
                formatted_line = f"{cmd:<14} {desc}"
                self.add_option(formatted_line)

        if matched_cmds:
            self.display = True
            self.highlighted = 0
        else:
            self.display = False

        return matched_cmds
