import os
from textual.widgets import Static
from models_dev import format_context_tokens

class StatusFooter(Static):
    """Двухстрочная информационная строка состояния под чатом"""
    can_focus = False
    ALLOW_SELECT = False

    def update_status(
        self,
        provider_key: str,
        model_name: str = "",
        directory: str = "",
        active_bg_tasks: int = 0,
        total_tokens: int = 0,
        context_window: str = "128k",
        context_limit: int = 128000,
        cost_usd: float = 0.0
    ) -> None:
        if not directory:
            directory = os.path.basename(os.path.realpath(os.getcwd())) or "root"

        # Строка 1 Слева: Окружение
        dir_text = f"Dir: {directory}"
        prov_text = f"Provider: {provider_key}" if provider_key else "Provider: default"
        model_text = f"Model: {model_name}" if model_name else ""
        left_1_parts = [dir_text, prov_text]
        if model_text:
            left_1_parts.append(model_text)
        left_1 = "  │  ".join(left_1_parts)

        # Строка 1 Справа: Фоновые задачи
        right_1 = f"Tasks: {active_bg_tasks} bg" if active_bg_tasks > 0 else ""

        # Строка 2 Слева: Прогресс контекста
        pct = (total_tokens / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        bar_str = "█" * filled + "░" * (bar_len - filled)
        used_formatted = format_context_tokens(total_tokens)
        left_2 = f"Context: [{bar_str}] {pct:.1f}% ({used_formatted}/{context_window})"

        # Строка 2 Справа: Токены и Стоимость
        tokens_text = f"Tokens: {total_tokens:,} tok"
        cost_text = f"Cost: ${cost_usd:.4f}"
        right_2 = f"{tokens_text}  │  {cost_text}"

        line1 = self._justify(left_1, right_1)
        line2 = self._justify(left_2, right_2)

        self.update(f"{line1}\n{line2}")

    def _justify(self, left: str, right: str) -> str:
        if not right:
            return left
        # Учитываем padding (padding: 0 3 дает отступы по 3 символа слева и справа)
        width = self.size.width - 6 if self.size and self.size.width > 6 else 100
        padding = max(2, width - len(left) - len(right))
        return f"{left}{' ' * padding}{right}"
