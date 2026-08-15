# UI_REFACTOR_REVIEW.md

> **СТАТУС:** план готов, рефакторинг не начат. Исследование выполнено read-only explorer-ом. Core уже отрефакторен в слои `domain → application → infrastructure` (см. ARCH_REFACTOR_REVIEW.md). Эта задача — аналог для UI (`widgets/`, `app.py`, `app.tcss`, `cli.py`).

## 1. Ключевые наблюдения

- **Образец расщепления уже есть:** `chat_view.py` → re-export шim; бизнес-виджеты живут в `chat_container/messages/markdown/tools/toolcall/welcome`.
- **core уже трёхслойный:** виджеты импортируют `core.application.*`, `core.infrastructure.*`, `core.domain.*`, плюс немного старого плоского нейминга (`core.permission_manager`, `core.role_registry`, `core.session_manager`).
- **Почти все core/tools-импорты в виджетах ленивые** (внутри ф-ций) — низкая связанность на уровне контракта; вынос логики безопасен.
- **`app.py` — единственная точка жёсткой сборки ядра** (TaskManager/SessionStore/ProviderManager/PermissionManager/RoleRegistry/tools.registry).
- **`patch.py` — глобальная мутация Textual** (монkeypatch `Widget.allow_select`, `Screen._forward_event`, `RichVisual.render_strips`, ...) + каскад в `chat_markdown._apply_chat_markdown_patches()`. Критичный изолированный узел.
- **Известный pre-existing баг:** `tests/ui/test_message_flow.py` висит (реальный цикл GenCanvas + `@work`, deadline `_wait_not_generating` 10s). Не артефакт переезда.

## 2. Целевая структура widgets/

```
widgets/
├── app/                        ← "умный" слой (composition root + команды + состояние)
│   ├── app.py                  ← перенос из корня (JohnstonApp)
│   ├── patch.py                ← ре-экспорт стаб → presentation/render_patch.py
│   ├── commands.py             ← из widgets/commands.py
│   ├── dispatch.py             ← диспетчер slash-команд (обёртка над commands)
│   ├── status_state.py         ← build_status_kwargs(app) -> dict  (из status_footer)
│   ├── session_state.py        ← read/write_session_persistence(app) (из session_persistence)
│   ├── ai_controller.py        ← generate_ai_response/GenCanvas-сборка (из message_flow)
│   ├── command_provider.py     ← список команд+скилов (из command_suggestions)
│   ├── role_service.py         ← toggle_role/RoleRegistry (из actions)
│   └── modal_screens.py        ← из widgets/modal_screens.py
├── mixins/                     ← композиционные части app (остаются; ядро-блоки выносятся)
│   ├── lifecycle.py            ← каркас compose/on_mount/on_unmount
│   ├── message_flow.py         ← тонкая обвязка событий
│   ├── session_persistence.py  ← вызовы session_state
│   └── actions.py              ← событийные обработчики (confirm_permission/ask_user + навигация)
├── presentation/               ← ЧИСТЫЕ рендер-виджеты, без core/tools импортов
│   ├── widgets/
│   │   ├── chat_messages.py, chat_markdown.py, chat_welcome.py
│   │   ├── chat_container.py (ChatView), chat_diff.py, chat_tools.py
│   │   ├── chat_toolcall.py, chat_input.py
│   │   ├── status_footer.py (рендер готового dict)
│   │   └── command_suggestions.py (рендер+поиск)
│   ├── screens/                ← переезд всей widgets/screens/*
│   └── render_patch.py         ← из widgets/patch.py (логику НЕ менять)
├── utils/                      ← ЧИСТЫЕ хелперы без textual/core
│   ├── lexer.py                ← из lexer_utils (чистый лексер)
│   ├── file_reader.py          ← из tool_helpers.read_file_content
│   └── text_processing.py      ← из chat_toolcall (чистые ф-ции)
└── adapters/                   ← re-export стабы для старых путей
    ├── chat_view.py (шim), tool_helpers.py, lexer_utils.py
    ├── commands.py, status_footer.py, screens/*.py
```

## 3. Матрица виджет ↔ core/tools

### Чистые (0 core/tools) — прямой переезд в presentation/
`chat_messages.py`, `chat_welcome.py`, `chat_diff.py`, `chat_tools.py`, `chat_container.py`, `chat_markdown.py`, `screens/ask_user.py`, `screens/base_modal.py`, `screens/base_selection.py`, `screens/constants.py`, `screens/resume.py`, `screens/rewind.py`, `screens/help.py`.

### Требуют решения (вынос логики или оставить точечные импорты)

| Файл | Зависимости ядра | Действие |
|---|---|---|
| `app.py` | всё (сборка) | composition root; оставить, НЕ дробить |
| `patch.py` | глобальная мутация Textual | ✅ переезд в `presentation/render_patch.py`, логику НЕ менять |
| `status_footer.py` | catalog, format_context_tokens, SkillManager, collect_current_tasks, THEME_* | ⚠️ вынести сборку в `app/status_state.py`; остальное переезд |
| `message_flow.py` | generate_ai_response/GenCanvas/ensure_provider_ready | ⚠️ вынести канвас-сборку в `app/ai_controller.py` |
| `session_persistence.py` | is_ui_visible_user_message, PromptBuilder, estimate_tokens | ⚠️ вынести в `app/session_state.py` |
| `commands.py` | provider.actions, session.actions, SkillManager, catalog | ⚠️ обернуть в `app/dispatch.py` |
| `command_suggestions.py` | SkillManager, COMMAND_REGISTRY | ⚠️ список команд → `app/command_provider.py` |
| `actions.py` | RoleRegistry, PermissionManager (лениво) | ⚠️ toggle_role → `app/role_service.py`; rest остаётся |
| `git_metrics_mixin.py` | get_git_info (лениво) | minor: _git_branch → core; diff подпроцесс оставить |
| `tool_helpers.py` | tools.registry.* | ре-экспорт; read_file_content → `utils/file_reader.py` |
| `lexer_utils.py` | make_git_diff, normalize_tool_args (лениво) | лексер → `utils/lexer.py`; diff-построение → core |
| `chat_input.py` | platform.paths, get_clipboard_image_or_file | оставить (легитимная инфра); пути через utils-обёртку |
| `chat_toolcall.py` | display.extract_tool_display, tasks.output.process_carriage_returns | оставить ленивые импорты; не дробить render_content |
| `screens/{linters,mcp,skills,permissions,permission_confirm,model,tasks,subagent_screen}.py` | менеджеры/инфра | оставить правильные инъекции менеджера; переезд |
| `screens/thinking_effort.py` | display_thinking_effort | 1 хелпер — оставить, переезд |

**Вывод:** больше всего ядра в `status_footer` (сбор), `message_flow` (движок), `session_persistence` (сохранение), `commands` (диспетчер). Остальное — легитимные точечные обращения.

## 4. Кандидаты на вынос в application-слой

1. `collect_status_for_footer(app) -> dict` (из status_footer.refresh_footer) → `app/status_state.py`.
2. `build_ai_generation_canvas(app)` + `generate_ai_response` → `app/ai_controller.py`.
3. `read/write_session_persistence(app)` + пересчёт токенов → `app/session_state.py`.
4. `build_edit_diff_text/generate_chunk_unified_diff` → `core.application.display` (убрать из lexer_utils).
5. `_git_branch` → отвязать от get_git_info (уже в core).
6. `action_toggle_role` (RoleRegistry) → `app/role_service.py`.
7. `get_all_command_suggestions` → `app/command_provider.py`.

> Принцип: выносим не ядро-зависимости сами по себе, а **накопление/сборку данных** (state) и **долгие операции** (генерация/сохранение). В виджетах остаётся рендер и событийная обвязка.

## 5. Фазы рефакторинга (каждая = зелёный pytest ≈ без test_message_flow)

- Phаза 0 — ✅ **Контрольный базлайн:** `pytest -n auto` без `test_message_flow` → зафиксировать зелёный. Починить ред-фейлы до изменений.
- Фаза 1 — **Переезд чистых виджетов:** `chat_messages, chat_welcome, chat_diff, chat_tools, chat_markdown, chat_container` → `presentation/widgets/`; обновить `chat_view.py`-re-export.
- Фаза 2 — **Переезд screens пачкой** (без смены логики): `widgets/screens/*` → `presentation/screens/`; `modal_screens.py` → `app/`.
- Фаза 3 — **Вынос хелперов в utils:** `lexer_utils` → `utils/lexer.py`, `tool_helpers.read_file_content` → `utils/file_reader.py`.
- Фаза 4 — **Вынос сборки состояния:** `app/{status_state, session_state, ai_controller, command_provider}.py`; переключить `status_footer/message_flow/session_persistence/command_suggestions/actions`.
- Фаза 5 — **Диспетчер commands:** выделить `app/commands.py` + `app/dispatch.py`.
- Фаза 6 — **Composition root:** перенести `app.py` → `widgets/app/app.py`.
- Фаза 7 — **Уборка стабов:** удалить лишние adapters/`__init__`, `ruff check .`, полный pytest (кроме бага). Conventional commits по каждой фазе.

## 6. Риски и митигации

1. **Textual monkeypatch (`patch.py`)** — глобальные правки; порядок импортов меняет момент применения патчей. → патчить одинаково рано; НЕ переписывать патчи, только перемещать (идемпотентность сохранить).
2. **Глобальные singletons** (`get_mcp_manager`, `PermissionManager._instance`, `RoleRegistry._instance`, `catalog`). → сборку `app.py` двигать последней; НЕ вводить новые singletons на ранних фазах.
3. **re-export-шум `chat_view`/`chat_container`** — много `from widgets.chat_view import ...`. → стабы обязательны, не удалять до grep-подтверждения.
4. **Известный баг `test_message_flow`** — исключить из прогона; разбирать отдельно (попутно на Фазе 4, не закладывать).
5. **UI-тесты** (`test_patch`, `test_status_footer`, `test_permission_confirm_screen`, `test_screens_pilot`) — зеркально переезжают вместе с источником; до фаз 2/4 не менять.
6. **`status_footer` — высокосвязанный узел.** Sensory-переезд без выноса состояния не даст выгоды; logic-часть — только на Фазе 4.
7. **Не создавать `widgets/app/` на ранних фазах** — рано завяжут старые модули на новые.

### Что НЕ двигать / не трогать
- Сам код патчей `widgets/patch.py` + `chat_markdown._apply_chat_markdown_patches` — только переезд файла.
- `app.py`-сборку менеджеров/singletons — только финальная фаза.
- Внутренности `chat_toolcall.render_content` / FormattingMixin — не дробить.
- `commands.py` handle_slash_command-ветку (homoglyphs, parse_frontmatter) — обернуть registry, не переписывать.
- Логику `ask_user` wizard — только переезд, без изменений.

---

**Итог:** движение от плоского `widgets/` с прямой сборкой данных в виджетах к `presentation (чистый рендер) / app (состояние+диспетчеры) / utils (хелперы)`, mixins оставляются тонкими, критичные узлы (patch, app.py, ask_user, toolcall) — изолируются.

## 7. Статус прогресса

| Фаза | Статус |
|---|---|
| Фаза 0 — контрольный базлайн | ✅ пройдено (2295 passed, 0 failed) |
| Фаза 1 — чистые виджеты → presentation/widgets | ✅ пройдено |
| Фаза 2 — screens → presentation/screens | ✅ пройдено |
| Фаза 3 — хелперы → utils | ✅ пройдено |
| Фаза 4 — состояние → app/ | 🔄 4b message_flow+actions+session_persistence |
| Фаза 5 — диспетчер commands | ✅ пройдено |
| Фаза 6 — composition root (app.py) | ✅ пройдено |
| Фаза 7 — уборка стабов, финал | ⬜ не начато |