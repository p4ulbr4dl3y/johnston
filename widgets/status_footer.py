import os
from textual.widgets import Static

class StatusFooter(Static):
    """Информационная строка состояния под чатом (директория, провайдер, модель, контекст, токены, стоимость)"""
    can_focus = False

    def update_status(
        self,
        provider_key: str,
        model_name: str = "",
        directory: str = "",
        total_tokens: int = 0,
        context_window: str = "128k",
        cost_usd: float = 0.0
    ) -> None:
        if not directory:
            directory = os.path.basename(os.path.realpath(os.getcwd())) or "root"

        dir_text = f"📁 {directory}"
        prov_text = f"⚡ {provider_key}" if provider_key else "⚡ default"
        model_text = f"🤖 {model_name}" if model_name else ""
        context_text = f"🧠 {context_window}" if context_window else ""
        tokens_text = f"🪙 {total_tokens:,} tok"
        cost_text = f"💲 ${cost_usd:.4f}"

        parts = [dir_text, prov_text]
        if model_text:
            parts.append(model_text)
        if context_text:
            parts.append(context_text)
        parts.extend([tokens_text, cost_text])

        status_line = "  │  ".join(parts)
        self.update(status_line)
