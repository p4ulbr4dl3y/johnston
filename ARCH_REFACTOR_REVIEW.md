# ARCH_REFACTOR_REVIEW.md

> **СТАТУС (финальный):** Рефакторинг выполнен (фазы 1-11). Core очищен от зависимостей на tools, кроме composition-root `provider_manager` и presentation-хелпера `application/display.py` (рендер tool-chips, см. ниже). Слоистая архитектура реализована. Тесты зелёные (2295 passed, ruff чист).

## Итоговое состояние

**Слои core/:**
- `domain/{defaults,entities,policies}` — чистые данные, сущности, политики
- `infrastructure/{adapters,mcp,platform,runtime,storage,tasks,errors}` — IO/транспорт/config
- `application/{generation,session,provider,rules,skills,linters}` — оркестраторы
- `base_provider/`, `adapters/` — движок и транспорт
- остаток в корне core/ — re-export обёртки + композиционные корни

**Выполнены все фазы:**
- 1: переезд листьев в слои
- 2: break цикла adapters
- 3-7: переезд утилит + DI core→tools (0 импортов), кроме рендер-хелпера
- 8-9: оркестраторы в application/, политики в domain/
- 10-11: git_checkpoint/storage, subagent_worktree/runtime, tool_*/application, permission+model+session политики/сущности в domain/

**Что осталось ре-export-обёртками (тонкие):** `git_checkpoint.py`, `subagent_worktree.py`, `tool_display.py`, `infrastructure/errors.py`.
**Жирные классы/корни (логика вынесена, классы остались):** `session_manager`, `models_catalog`, `role_registry`, `permission_manager`, `provider_manager` — их полная миграция требует точечного плана и не даст существенной выгоды сейчас.

**> Последующий хвост после финализации:** пустой мёртвый стаб `core/tool_helpers.py` удалён (0 потребителей).

**Известный pre-existing баг:** `tests/ui/test_message_flow.py` виснет (UI-тест Textual, не связан с рефакторингом).

## Прогресс рефакторинга

- ✅ **Фаза 1 — переезд листьев в слои:** `core/domain/defaults`, `core/infrastructure/{mcp,tasks,runtime,platform}`. Старые папки удалены.
- ✅ **Фаза 2 — разбивка `platform_utils`:** `core/infrastructure/platform/platform_utils.py`, `logging_setup.py`.
- ✅ **Фаза 3 — разрыв цикла `base_provider ⇄ adapters`:** чистые adapter-хелперы → `core/infrastructure/adapters/base.py`; `new_tool_call_id` там же. `check_httpx_response_status` остался в adapters.
- ✅ **Фаза 4 — переезд чистых утилит:** `format_tool_error` → `core/infrastructure/errors.py`; `tail_output` → `core/infrastructure/tasks/output.py`.
- ✅ **Фаза 5 — DI core→tools (агент):** `execute_tool`, `get_default_tools`, `process_image_file_sync`, `normalize_tool_name` инъекции в `BaseAgent`/`ToolMixin`. Сборочный узел в `provider_manager.py`.
- ✅ **Фаза 6 — DI permission/role:** `permission_manager`, `role_registry` больше не импортят `tools.registry`. Wiring в `app.py`.
- ✅ **Фаза 7 — `subagent_stream`:** `_truncate_subagent_result` → `core.infrastructure.tasks.output.truncate_subagent_result`.

**Итог зависимостей:** `core→tools` импортов нет, кроме двух санкционированных: composition-root `provider_manager` и presentation-хелпер `application/display.py` (рендер tool-chips для UI — им пользуется движок агента для генерации `tool_result`-label, потому это не виджет, а слой ядра). Циклы разорваны. `domain` остаётся чистым слоем ниже всех.

## 1. Архитектурный анализ


### Объективная карта зависимостей (grep по топ-уровневым импортам)

**Листья (0 зависимостей на core/tools):**
`token_util`, `thinking_effort`, `task_collection`, `tool_display`, `frontmatter`, `circuit_breaker`, `platform_utils`, `fs_signature`, `git_utils`, `core/adapters/base.py`, `core/tasks/{task,output,manage}.py`, `core/roles/{prompt,provider,resolve}.py`, `core/defaults/*`, `core/mcp_manager/process_client.py`.

**Средний слой (листья + ядро):**
- `config.py` → `platform_utils`
- `config_helpers.py` → `platform_utils`
- `session_manager.py` → `config`, `fs_signature`, `platform_utils`
- `skill_manager.py` → `config`, `defaults/*(git_excludes, skills.loader)`, `frontmatter`, `fs_signature`
- `markdown_scanner.py` → `config`, `frontmatter`, `fs_signature`
- `roles/tools.py` → `defaults`
- `tasks/shell_task.py` → `platform_utils`, `tools.base`

**Смешанный узел с обратной связью:**
- `prompt_builder.py` → `defaults.prompts`, `git_utils`, `skill_manager`, **`tools.invoke_subagent`** (!!)
- `role_registry.py` → `defaults`, `frontmatter`, `markdown_scanner`, **`tools.base`** (!!)
- `permission_manager.py` → `config`, `defaults.config`, `platform_utils`, и **`tools.registry`** (ленивый, в ф-циях)

**Цикл провайдерного стека:**
- `base_provider/agent.py` → **`core.adapters.base`**, `models_catalog`, `prompt_builder`, `token_util`, `tool_display`, `tools.registry`, `tools.base`
- `base_provider/errors.py` → **`core.adapters.base`**
- `adapters/{openai,anthropic,gemini,ollama}.py` → **`core.base_provider.tools`**, `thinking_effort`, `adapters.base`
- `base_provider/tools.py` → `models_catalog`, `prompt_builder`, `token_util`, + ленивые `tools.registry`, `role_registry`

### Критические находки

**1. Жёсткий цикл `base_provider ⇄ adapters`.** Агент движок (`agent.py`, `errors.py`) импортирует транспортные хелперы из `adapters/base.py` (extract_image_payload, image_url_block, parse_tool_call_args). Одновременно каждый адаптер импортирует `base_provider/tools.py` (new_tool_call_id). Два слоя ссылаются друг на друга. Правильно: адаптеры — транспорт, должны зависеть от движка, а не наоборот. Сейчас движок тянет хелперы из слоя, который выше него.

**2. `prompt_builder.py` → `tools.invoke_subagent`.** Сборщик промптов (чистое ядро) протекает на предметный слой инструментов. Это разворот зависимости: engine тянет tool-класс.

**3. Оборотный цикл core↔tools (мягкий, ленивый, но хрупкий).** `tools.registry` пишет `permission_manager` по имени в ф-циях; `role_registry`/`prompt_builder` импортят `tools.*`; `tools.*` импортируют `linters_manager`, `subagent_worktree`, `session_manager`, `tasks`, `platform_utils`. Цикл: `core.prompt_builder` → `tools.invoke_subagent` → `core.defaults` (безопасно при загрузке, т.к. defaults — листья). Все обходы — это клей на ленивых импортах внутри функций, что хрупко и заметает настоящую топологию.

**4. Плоские utility-пакеты с чужим смыслом.** `tool_display.py`, `tool_helpers.py`, `task_collection.py`, `fs_signature.py` — набор helpers без доменной группировки. Нет единого `infra/` слоя.

**5. Singleton-синглтоны с привязкой к конфигу загрузки.** `PermissionManager`, `RoleRegistry`, `SkillManager`, `models_catalog.catalog` — global-state через `get_instance()`, читают `CONFIG_FILE`/cwd из функций. Тестируемость и инверсия зависимостей зажаты.

**6. Нет чёткой границы домен/application/infrastructure.** `ai_generator.py` (оркестратор бизнес-цикла агента) в одной папке с `platform_utils.py` и `token_util.py`. Уровневая ошибка повсюду.

---

## 2. Предлагаемая структура

Слои: **domain → application → infrastructure**. Инструменты (`tools/`) остаются отдельным предметным слоем за application, но без обратных ссылок ядра на них.

```
core/
  domain/                        # чистые модельки/знание, 0 зависимостей на tools/UI/adapters
    entities/
      session.py                 # Session, SessionStoreDraft (модель, статусы)   ← из session_manager
      role.py                    # AgentRole, normalize_role_scope                ← из role_registry
      message.py                 # user/bot/thinking сообщения, is_ui_visible хелпер ← из session_manager/tool_display
      model.py                   # ModelRecord                                   ← из models_catalog
      checkpoint.py              # GitCheckpoint                                  ← из git_checkpoint
    policies/
      role_policy.py             # _tool_policy_result, role_tool_error, SubagentPolicy  ← из role_registry
      permission_policy.py       # check_permission логика (чистая)              ← из permission_manager (без IO)
    value_objects/
      pathops.py                 # resolve_path, tail_output, truncate_output    ← из tools/base+utils
      diff.py                    # make_unified_diff                              ← из tools/base/git_utils
    defaults/                    # (переезд целиком)
      config.py prompts.py tools.py providers.py linters.py git_excludes.py skills/

  application/                   # оркестрация, use-cases; знает domain+infra, но не tools/UI
    agent/
      engine.py                  # BaseAgent (цикл стриминга)                     ← из base_provider/agent
      tool_loop.py               # ToolMixin, dispatch через registry-интерфейс    ← из base_provider/tools
      compaction.py              # CompactionMixin, should_compact
      errors.py                  # format_api_error (без импорта адаптеров!)      ← из base_provider/errors
      context.py                 # build_prompt_context, new_tool_call_id         ← из base_provider/tools
    session/
      manager.py                 # SessionStore (persistence)                     ← из session_manager
      actions.py                 # new/resume/compact/rewind                      ← из session_actions
      stream.py                  # record_subagent_step                           ← из subagent_stream
    provider/
      manager.py                 # ProviderManager                                ← из provider_manager
      actions.py                 # provider_actions                               ← из provider_actions
      catalog.py                 # CategoryRegistry (каталог)                     ← из models_catalog
    generation/
      ai_generator.py            # GenCanvas оркестратор                          ← из ai_generator
      prompt_builder.py          # PromptBuilder                                  ← из prompt_builder (убрать deps на tools)
    rules/
      permission.py              # PermissionManager (IO-обёртка над policy)      ← перенос
      rules.py                   # RulesManager                                   ← из rules_manager
      skills.py                  # SkillManager                                   ← из skill_manager
      linters.py                 # LintersManager                                 ← из linters_manager
    roles/
      registry.py                # RoleRegistry (IO load)                         ← из role_registry
      resolve.py apply.py provider.py prompt.py tools.py                          ← из core/roles/*

  infrastructure/                # IO/платформа/транспорт; листья, знают только друг о друге
    config/
      config.py config_helpers.py                                                 ← переместить
    storage/
      store.py                   # read_json/atomic_write_json/atomic_write_text  ← из platform_utils
      session_store.py           # сериализация сессий                            ← из core/platform_utils+session_manager
      fs_signature.py                                                              ← из fs_signature
    platform/
      platform_utils.py                                                           ← остаётся
      logging_setup.py
      paths.py                   # константы каталогов                            ← из config + platform_utils
    runtime/
      circuit_breaker.py token_util.py thinking_effort.py frontmatter.py
      markdown_scanner.py task_collection.py git_utils.py workflow.py           ← из subagent_worktree
    adapters/
      base.py                    # protocol-типы для транспорта (без логики цикла) ← из core/adapters/base
      openai.py anthropic.py gemini.py ollama.py                                   ← перенос (зависят от domain/application/policies)
    mcp/
      manager.py process_client.py                                               ← из mcp_manager
    tasks/
      task.py shell_task.py manage.py manager.py output.py                         ← из core/tasks

  unittest-helpers/              # (опционально) общие фейки для тестов
```

`tools/` — предметные исполнители, зависят только на `core.infrastructure` + интерфейс `PermissionPolicy` из `domain.policies`. Все ленивые импорты ядра из tools → вынести в интерфейсы DI.

---

## 3. Ключевые изменения (что↔куда и почему)

| Сейчас | Куда | Почему |
|---|---|---|
| `base_provider/agent.py` | `application/agent/engine.py` | Ядро применения, бизнес-цикл |
| `base_provider/errors.py` | `application/agent/errors.py` — **убрать import `adapters.base`** | Разорвать цикл; вынести пайплайн ошибок в `infra/adapters/base.py` как протокол, звать через DI |
| `base_provider/tools.py` | split: dispatcher → `application/agent/tool_loop.py`, чистые хелперы → `domain/pathops` + `application/agent/context.py` | Отделить исполнение от схемы |
| `adapters/*` | `infrastructure/adapters/*`, импорт только `new_tool_call_id` через `domain`/`application`, не `base_provider.tools` | Устранить верх-вниз связь |
| `session_manager.py` | split `domain/entities/session.py`(модель) + `infrastructure/storage/session_store.py`(IO) + `application/session/manager.py` | Модель чистая, IO в инфра |
| `models_catalog.py` | split `domain/entities/model.py` + `application/provider/catalog.py` | Знание ≠ операция |
| `role_registry.py` | split `domain/policies/role_policy.py`(чистая логика) + `application/roles/registry.py`(load) | Убрать `tools.base`-зависимость из политики |
| `permission_manager.py` | split `domain/policies/permission_policy.py`(прав`ил`) + `application/rules/permission.py`(IO) | Чистая проверка тестируема без файлов |
| `prompt_builder.py` | `application/generation/prompt_builder.py` — **убрать `tools.invoke_subagent`** через интерфейс | Разорвать core→tools |
| `platform_utils.py` | split `infrastructure/storage/store.py`(json IO) + `infrastructure/platform/*`(остальное) | Группировка по инфра-роли |
| `tool_display.py`, `tool_helpers.py`, `task_collection.py`, `fs_signature.py` | `infrastructure/*` по назначению | Меньше бессмысленных плоских микромодулей |

---

## 4. Критические проблемы и решения

1. **Цикл `base_provider ⇄ adapters`.** Решение: вынести транспортные хелперы (`extract_image_payload`, `parse_tool_call_args`, `image_url_block`) в `infrastructure/adapters/base.py` как чистые протоколы; движок через DI, адаптеры больше не знают о `base_provider.tools`. Порядок импорта выровняется строго вниз.

2. **`prompt_builder` → `tools.invoke_subagent`.** Решение: заменить на передачу дескриптора инструмента оркестратором (`application/generation`), чтобы ядро не знало конкретики tools.

3. **Всюду `core.*` ↔ `tools.*` перекрёстная связность.** Решение: запретить ядру импортить `tools`; `tools` знают только `infrastructure` + интерфейсы `domain.policies`. `permission_manager`/`role_registry` ленивые импорты `tools.registry` заменить на DI (инжект `normalize_tool_name`/`REGISTRY`).

4. **Разобщенный flat `core/*.py` без уровневых границ + singletornы (get_instance).** Решение: физически разбить по слоям (структура выше) и внедрять зависимости через конструкторы/DI, а не через module-global `get_instance`.

5. **`agent.py` тащит `AsyncOpenAI` напрямую (техдолг транспорта).** Решение: выделить единый `infrastructure/adapters/transport.py` — фабрику клиентов; движок не знает OpenAI-специфику (плюс gemini/ollama не переиспользуют).

---

## 5. Порядок рефакторинга

Фаза 0 — Клонировать в миграционные ветки, полный прогон `uv run pytest -n auto`, зафиксировать бейзлайн.

1. **Шаги без изменения поведения: перемещение файлов.** Сначала только листья/полностью изолированные: `defaults/*`, `token_util`, `thinking_effort`, `frontmatter`, `circuit_breaker`, `task_collection`, `fs_signature`, `git_utils`, `tasks/*`, `mcp_manager`, `roles/{provider,prompt,resolve}` — в новые папки. Обновить импорты. Каждый ход = зелёный pytest.
2. **Разбить `platform_utils`** на `storage`/`platform` без смены имён — самый генеративный хедер, вслед потянутся `config`, `session_manager`, `skill_manager`.
3. **Разорвать цикл адаптеров:** вынести `adapters/base.py`-хелперы в `infrastructure/adapters/base.py`; убрать `errors.py`→adapters. Это распутывает главный топологический узел.
4. **Вычистить core→tools:** удалить `prompt_builder→tools`; в `permission_manager`, `role_registry`, `base_provider/tools` заменить ленивые `from tools.registry` на DI-интерфейсы.
5. **Только потом раскладывать `session_*`, `models_catalog`, `prompt_builder`** на domain/application — потому что эти ф-ции уже зависят от выровненных листьев.
6. **Разбить `agent.py`** на `engine`/`tool_loop`/`context` + transport-фабрику (самый рискованный шаг).
7. **Домен-политики:** вынести чистую логику `role_registry` и `permission_manager` в `domain/policies`.
8. **DI-инверсия singleton-режимов/`get_instance`,** добавить фабрики для тестов.
9. Сокрытие `core/__init__` — оставить барьеры экспорта, финальный lint `uv run ruff check .`.

Порядок строится от безрисковых переездов к узлам с максимальной связностью; на каждом шаге слой ниже уже замкнут (не зависит от вышестоящего).

---

## 6. Риски и митигации

- **Циклы импорта на ранней стадии** (до фазы 4) → митигация: сначала перемещаем листья, потом узлы; цикл адаптеров ломаем раньше остальных рефакторингов.
- **Сломать поведение `ai_generator`** (крупнейший оркестратор, множество side-effects) → митигация: переместить последним (шаг 6+), удерживать `GenCanvas`-интерфейс без изменений.
- **Множество точечных импортов (`from core.X import Y`) у подвижных файлов** → митигация: grep по всем `core.*` перед каждым ходом; временные re-export-заглушки только на один-два коммита.
- **Singletornы + конфиг на модуль-уровне** (`CONFIG_FILE`, `PROJECTS_DIR`) мешают DI и тестам → митигация: выставлять через инфра-фабрику путей, инъекция в constructor.
- **Регресс тестов при разделе ролей/прав** → митигация: политики (чистая логика) покрыть отдельными юнит-тестами `tests/core/` до переезда; IO-обёртки — после.
- **`tools/*` останутся без ядра** → митигация: явные интерфейсные протоколы (PermissionPolicy, ToolRegistry) в `domain/policies`, мок в тестах.

---

**Итог:** движение от плоского `core/` с мягкими циклами к трёхслойному `domain → application → infrastructure`, инструменты за границей через протоколы.

---

## 7. Результаты независимого ревью (explorer-ревьюер, read-only)

Проведено внешнее ревью качества рефакторинга. **Вердикт: 4/5 — устойчивый, чистый рефакторинг.** Найдены 4 мелких хвоста (HIGH — нет):

| Проблема | Seve | Статус |
|---|---|---|
| `domain/policies/role_policy.py` → `infrastructure.errors` (нарушение домен-чистоты) | MED | ✅ Исправлено: `format_tool_error` перенесён в `domain/defaults/errors.py`; `infrastructure/errors.py` стал re-export |
| `application/display.py` лениво тянет `tools.registry` (core→tools вне composition-root) | MED | ✅ Легализовано в доке как санкционированный рендер-хелпер (им пользуется движок агента для `tool_result`-label, поэтому не виджет) |
| Пустой мёртвый стаб `core/tool_helpers.py` | LOW | ✅ Удалён (0 потребителей, все юзают `widgets.tool_helpers`) |
| `import *` без `__all__` в re-export `subagent_worktree.py` | LOW | ✅ Исправлено: явный импорт + `__all__` |

**Что отлично отмечено ревьюером:** фазы подготовки (ленивые tools-импорты вынесены в функции), разрыв цикла `base_provider⇄adapters`, полная очистка `prompt_builder→tools`, автономность `base_provider`, чистота новых domain-модулей (`entities/session`, `policies/{permission,model_catalog}`), сохранение сигнатур (`extract_context_length`, `format_tool_error`), отсутствие дублирования/мёртвого кода.

**Уточнение к допустимым core→tools:** после всех фиксов полный core→tools сводится к двум санкционированным точкам: composition-root `provider_manager` + рендер-хелпер `application/display.py`. `domain` остаётся строго чистым слоем (0 зависимостей на infrastructure/application/tools).