from textual.widgets import Static

class StatusFooter(Static):
    """Информационная строка состояния под чатом"""
    can_focus = False

    def update_status(self, provider_key: str, model_name: str = "", session_id: str = "") -> None:
        prov_text = f"⚡ {provider_key}" if provider_key else "⚡ default"
        model_text = f"🤖 {model_name}" if model_name else ""
        
        parts = [prov_text]
        if model_text:
            parts.append(model_text)
        if session_id:
            parts.append(f"📁 {session_id[:18]}")

        status_line = "  │  ".join(parts)
        self.update(status_line)
