# AI Agents and Providers in Johnston Chat

The project uses a modular architecture for configuring and executing AI agents. Users can switch providers and models on the fly directly from the interface or via slash commands.

---

## Agent Architecture

```mermaid
graph TD
    PM[ProviderManager core/provider_manager.py] -->|Loads .py configs| P[Providers ~/.johnston/providers/]
    PM -->|Creates agent| Agent[BaseAgent core/base_provider.py]
    Agent -->|Builds prompts| PB[PromptBuilder core/prompt_builder.py]
    Agent -->|Requests via OpenAI API| LLM[LLM API / OpenCode / Custom]
    Agent -->|Invokes tools with ToolContext| Tools[tools/registry.py]
```

---

## 1. Providers

Each provider is described by a separate `.py` file in the local `providers/` directory of the project.
When the application starts, `ProviderManager` ([core/provider_manager.py](file:///Users/yegor/johnston/core/provider_manager.py)) dynamically imports these files.

### Provider Configuration Example (`providers/opencode.py`):
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
            "name": "read",
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

## 2. Base Agent Class (`BaseAgent`) and `PromptBuilder`

Defined in [core/base_provider.py](file:///Users/yegor/johnston/core/base_provider.py).
* Uses `openai.AsyncOpenAI` client.
* Delegates dynamic prompt and tool schema construction to `PromptBuilder` ([core/prompt_builder.py](file:///Users/yegor/johnston/core/prompt_builder.py)) considering active MCPs, Skills, and mode (Plan/Build).
* **Dynamic metadata and project instructions**: `PromptBuilder` automatically appends to system prompt:
  * Environment metadata: CWD, local time, OS, Git status (current branch, modified/untracked files count).
  * Project instructions: contents of `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, or `CONVENTIONS.md` from the working directory.
* **Automatic and Manual Context Compaction**:
  * `BaseAgent` monitors history token usage and automatically compacts history via LLM summaries upon reaching 75% of context window limit.
  * Manual compaction is available via `/compact` slash command.
* Implements `stream_steps(user_text)` method:
  * Streams token chunks from the model.
  * Parses reasoning/thinking chains and renders them in the UI.
  * Recognizes tool calls (`tool_calls`), delegates execution to `execute_tool`, and sends results back to the model.

---

## 3. Tool Execution and `ToolContext`

Tools are isolated in [tools/](file:///Users/yegor/johnston/tools/).
All available tools are registered in [tools/registry.py](file:///Users/yegor/johnston/tools/registry.py). UI isolation from business logic is guaranteed via `ToolContext` ([tools/context.py](file:///Users/yegor/johnston/tools/context.py)). Built-in tools include: `read`, `create`, `edit`, `bash`, `glob`, `grep`, `list_dir`, `ask_user`, `skill`, `call_mcp_tool`, `manage_task`, `switch_to_action`, `subagent`, `view_image`. Large output truncation is handled via `truncate_output`.

### How to Add a New Tool:
1. Create `tools/my_tool.py` inheriting from `BaseTool`:
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
2. Register the class in `TOOL_CLASSES` inside [tools/registry.py](file:///Users/yegor/johnston/tools/registry.py).
3. Tool schemas are pulled automatically via `get_default_tools()`. Manual `TOOLS` overrides in provider configs are not required!

---

## 4. Slash Commands and Action / Explore Modes

All slash commands are handled in [commands.py](file:///Users/yegor/johnston/commands.py) with automatic normalization of Cyrillic homoglyphs (to handle wrong keyboard layout input).

### Modes:
* **Action** (`/action`, aliases: `/build`, `/code`) — standard execution mode with full permissions for creating/editing files and executing bash commands.
* **Explore** (`/explore`, aliases: `/plan`, `/ask`) — read-only exploratory mode (code exploration, Q&A, planning). Direct code modifications are prohibited.

### Available Slash Commands:
* `/action` — enable `action` execution mode (`/build`, `/code`).
* `/explore` — enable `explore` read-only mode (`/plan`, `/ask`).
* `/mode` — toggle mode (`action` <-> `explore`).
* `/compact` — force history compaction.
* `/init` — interactive generation/update of `AGENTS.md` for current repository.
* `/connect` — connect provider and setup API key (`/provider` alias).
* `/models` — select model grouped by provider.
* `/skills`, `/mcp` — manage skills and MCP servers.
* `/tasks` — view and manage background tasks.
* `/rewind`, `/resume` — rewind chat history or resume session.
* `/new`, `/help` — start new chat / view keyboard shortcuts help.

### Shortcuts & Switching:
* `Shift+Tab` — quick toggle between `action` and `explore`.
* `SwitchToAction` (`tools/switch_to_action.py`) tool is invoked by model AFTER explicit user confirmation to switch from `explore` to `action`.

---

## 5. Subagents (Subagents & Subagent Tool)

The project supports running autonomous isolated subagents for subtasks:
* **`SubagentTool`** (`tools/subagent.py`): tool to launch a subtask subagent.
  * `subagent_type`: `"general"` (multi-step) or `"explore"` (fast code search).
  * `background`: `false` (synchronous waiting for result in `<task_result>`) or `true` (background async execution with auto notification on completion).
* **Isolation**: subagents run in isolated `BaseAgent` context without recursive access to `Subagent` tool.

---

## 6. Testing and Linting

All unit tests are isolated in [tests/](file:///Users/yegor/johnston/tests/).

* **Run tests**:
  ```bash
  uv run python -m unittest discover -s tests
  ```
* **Run linter**:
  ```bash
  uv run ruff check .
  ```

---

## 7. UI and Design System (Monochrome Slate)

The project uses a monochrome design system based on Textual TCSS ([app.tcss](file:///Users/yegor/johnston/app.tcss)), with color constants centralized in [core/config.py](file:///Users/yegor/johnston/core/config.py):
* **Accent Color**: Pure white (`#ffffff` / `THEME_PRIMARY`) for user text, active options in OptionList/suggestions menu, and main titles.
* **Background Palette**: `#09090b` (`THEME_BG` — chat screen), `#18181b` (`THEME_CARD` — cards, input field, popups, Toast notifications, footer), `#27272a` (`THEME_BORDER` — borders and dividers).
* **Toast Notifications**: `#18181b` cards with monochrome left accent bar (`#ffffff` / `#a1a1aa`).
* **Welcome Screen**: `WelcomeWidget` splash screen with `johnston` logo centered in empty chat.
