from textual.widgets import OptionList

COMMANDS = [
    ("/help", "Help and keybindings"),
    ("/resume", "Rollback chat history to a message"),
]

class CommandSuggestions(OptionList):
    """Выпадающее меню подсказок в стиле OpenCode / Claude CLI (оранжевая плашка, 2 колонки)"""
    
    can_focus = False

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
                # Команда слева (16 символов), описание справа
                formatted_line = f"{cmd:<14} {desc}"
                self.add_option(formatted_line)

        if matched_cmds:
            self.display = True
            self.highlighted = 0
        else:
            self.display = False

        return matched_cmds
