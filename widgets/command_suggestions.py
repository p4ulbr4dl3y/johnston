from textual.widgets import OptionList

COMMANDS = [
    ("/help", "💡 Открыть справку по командам"),
    ("/resume", "↺ Откат истории чата к выборанному сообщению"),
]

class CommandSuggestions(OptionList):
    """Выпадающее меню автодополнения слэш-команд"""
    
    can_focus = False

    def update_query(self, text: str) -> list[str]:
        """Обновление списка совпадений по текущему тексту"""
        self.clear_options()
        
        cleaned = text.strip().lower()
        if not cleaned.startswith("/") or " " in cleaned:
            self.display = False
            return []

        matched_cmds = []
        for cmd, desc in COMMANDS:
            if cmd.startswith(cleaned):
                matched_cmds.append(cmd)
                self.add_option(f"{cmd}  —  {desc}")

        if matched_cmds:
            self.display = True
            self.highlighted = 0
        else:
            self.display = False

        return matched_cmds
