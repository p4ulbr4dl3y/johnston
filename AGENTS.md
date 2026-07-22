# AI Agents and Providers in Johnston Chat

В проекте используется модульная архитектура для настройки и выполнения AI-агентов. Пользователь может переключать провайдеров и модели "на лету" прямо из интерфейса или через слэш-команды.

---

## Архитектура Агентов

```mermaid
graph TD
    PM[ProviderManager core/provider_manager.py] -->|Загрузка .py конфигураций| P[Providers ~/.johnston/providers/]
    PM -->|Создание агента| Agent[BaseAgent core/base_provider.py]
    Agent -->|Сборка промптов| PB[PromptBuilder core/prompt_builder.py]
    Agent -->|Запросы через OpenAI API| LLM[LLM API / OpenCode / Custom]
    Agent -->|Вызов инструментов с ToolContext| Tools[tools/registry.py]
```

---

## 1. Провайдеры (Providers)

Каждый провайдер описывается отдельным `.py` файлом в локальной директории `providers/` проекта.
При старте приложения `ProviderManager` ([core/provider_manager.py](file:///Users/yegor/tui/core/provider_manager.py)) динамически импортирует эти файлы.

### Пример конфигурации провайдера (`providers/opencode.py`):
```python
try:
    from core.base_provider import BaseAgent
except ImportError:
    from base_provider import BaseAgent

NAME = "OpenCode Go (DeepSeek v4 Flash)"
KEY = "opencode"
DESCRIPTION = "OpenCode Go agent (DeepSeek v4 Flash) with tools"

BASE_URL = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"
API_KEY = "sk-..."

SYSTEM_PROMPT = "You write code..."
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read file content.",
            "parameters": { ... }
        }
    }
]

class Agent(BaseAgent):
    def __init__(self, api_key: str = API_KEY, model: str = MODEL, base_url: str = BASE_URL):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            system_prompt=SYSTEM_PROMPT,
            tools=TOOLS,
            provider_key=KEY
        )
```

---

## 2. Базовый класс агента (`BaseAgent`) и `PromptBuilder`

Определен в [core/base_provider.py](file:///Users/yegor/tui/core/base_provider.py).
* Использует асинхронный клиент `openai.AsyncOpenAI`.
* Делегирует динамическую сборку промптов и схем инструментов в `PromptBuilder` ([core/prompt_builder.py](file:///Users/yegor/tui/core/prompt_builder.py)) с учетом активных MCP, навыков (Skills) и режима (Plan/Build).
* **Динамические метаданные и инструкции проекта**: `PromptBuilder` автоматически добавляет в системный промпт:
  * Метаданные окружения: CWD, локальное время, ОС, состояние Git (текущая ветка, количество измененных/неотслеживаемых файлов).
  * Инструкции проекта: содержимое файлов `AGENTS.md`, `CLAUDE.md`, `.cursorrules` или `CONVENTIONS.md` из рабочей директории.
* **Автоматическая и ручная компактизация контекста**:
  * `BaseAgent` отслеживает объем токенов истории и при достижении порога в 75% от лимита контекстного окна автоматически выполняет сжатие (компактизацию) истории через LLM-резюме.
  * Ручная компактизация доступна через слэш-команду `/compact`.
* Реализует метод `stream_steps(user_text)`:
  * Получает поток токенов (chunks) от модели.
  * Парсит мыслительные цепочки (reasoning/thinking) и выводит их в UI.
  * Распознает вызовы инструментов (`tool_calls`), передает их в реестр `execute_tool` и отправляет результаты обратно модели.

---

## 3. Выполнение Инструментов (Tools) и `ToolContext`

Инструменты изолированы в директории [tools/](file:///Users/yegor/tui/tools/).
Все доступные инструменты регистрируются в [tools/registry.py](file:///Users/yegor/tui/tools/registry.py). Изоляция UI от бизнес-логики обеспечивается объектом `ToolContext` ([tools/context.py](file:///Users/yegor/tui/tools/context.py)). Встроенные инструменты включают: `Read`, `Create`, `Edit`, `Bash`, `Glob`, `Grep`, `ListDir`, `AskUser`, `Skill`, `ManageTask`, `PlanExit`, `Subagent`. Для корректной оптимизации вывода больших ответов используется утилита усечения `truncate_output`.

### Как добавить новый инструмент:
1. Создайте файл `tools/my_tool.py`, унаследовав `BaseTool`:
   ```python
   from tools.base import BaseTool

   class MyCustomTool(BaseTool):
       name = "MyToolName"
       description = "What this tool does"
       schema = {
           "type": "function",
           "function": {
               "name": "MyToolName",
               "description": "What this tool does",
               "parameters": { ... }
           }
       }

       async def execute(self, args: dict, app=None) -> str:
           ctx = self._ensure_context(app)
           ctx.notify("Executing tool...")
           return "Result string"
   ```
2. Зарегистрируйте класс в `TOOL_CLASSES` внутри [tools/registry.py](file:///Users/yegor/tui/tools/registry.py).
3. Схема инструмента подтягивается автоматически через `get_default_tools()`. Переопределять `TOOLS` вручную в конфигах провайдеров не требуется!

---

## 4. Слэш-команды и Режимы Action / Explore

Все слэш-команды обрабатываются в [commands.py](file:///Users/yegor/tui/commands.py) с поддержкой автоматической нормализации кириллических омоглифов (для устранения ошибок ошибочной раскладки клавиатуры).

### Режимы работы:
* **Action** (`/action`, алиасы: `/build`, `/code`) — стандартный режим исполнения с полным доступом к созданию/редактированию файлов и выполнению bash-команд.
* **Explore** (`/explore`, алиасы: `/plan`, `/ask`) — исследовательский read-only режим (исследование кода, ответы на вопросы, составление планов). Прямое изменение кода запрещено.

### Доступные слэш-команды:
* `/action` — включить режим исполнения `action` (`/build`, `/code`).
* `/explore` — включить исследовательский режим `explore` (`/plan`, `/ask`).
* `/mode` — переключить режим (`action` <-> `explore`).
* `/compact` — выполнить принудительную компактизацию истории диалога.
* `/init` — интерактивный запуск генерации/обновления инструкции `AGENTS.md` для текущего репозитория.
* `/connect` — подключение провайдера и настройка API-ключа (`/provider` — алиас).
* `/models` — выбор модели с группировкой по провайдерам.
* `/skills`, `/mcp` — управление навыками и MCP-серверами.
* `/tasks` — просмотр и управление фоновыми задачами.
* `/rewind`, `/resume` — откат истории или возобновление сессии.
* `/new`, `/help` — создание нового чата / справка по горячим клавишам.

### Горячие клавиши и переключение:
* `Shift+Tab` — быстрая клавиша переключения `action` <-> `explore`.
* Инструмент `SwitchToAction` (`tools/switch_to_action.py`) вызывается моделью ПОСЛЕ явного подтверждения пользователя для переключения из `explore` в `action`.

---

## 5. Субагенты (Subagents & Subagent Tool)

Проект поддерживает запуск автономных изолированных субагентов для подзадач:
* **`SubagentTool`** (`tools/subagent.py`): инструмент для создания субагента подзадачи.
  * `subagent_type`: `"general"` (мультишаговый) или `"explore"` (быстрый поиск кода).
  * `background`: `false` (синхронное ожидание результата в `<task_result>`) или `true` (фоновое асинхронное исполнение с авто-уведомлением в чате по финишу).
* **Изоляция**: субагент запускается в изолированном контексте `BaseAgent` без рекурсивного доступа к инструменту `Subagent`.

---

## 6. Тестирование и Линтинг

Все юнит-тесты изолированы в директории [tests/](file:///Users/yegor/tui/tests/).

* **Запуск тестов**:
  ```bash
  uv run python -m unittest discover -s tests
  ```
* **Запуск линтера**:
  ```bash
  uv run ruff check .
  ```

---

## 7. UI и Дизайн-система (Monochrome Slate)

Проект использует монохромную дизайн-систему на базе Textual TCSS ([app.tcss](file:///Users/yegor/tui/app.tcss)), константы цвета которой централизованы в [core/config.py](file:///Users/yegor/tui/core/config.py):
* **Акцентный цвет**: Чистый белый (`#ffffff` / `THEME_PRIMARY`) для текста сообщений пользователя, активных выделений в OptionList/меню подсказок и главных заголовков.
* **Палитра фона**: `#09090b` (`THEME_BG` — экран чата), `#18181b` (`THEME_CARD` — карточки, инпут ввода, всплывающие окна, уведомления Toast, футер), `#27272a` (`THEME_BORDER` — бордеры и разделители).
* **Уведомления (Toast)**: Плашки `#18181b` с монохромной левой акцентной полосой (`#ffffff` / `#a1a1aa`).
* **Экран приветствия**: Заставка `WelcomeWidget` с логотипом `johnston` по центру пустого чата.
