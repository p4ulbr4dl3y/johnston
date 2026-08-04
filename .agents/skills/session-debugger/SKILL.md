---
name: session-debugger
description: Debugs Johnston and agent chat sessions. Use when given a session ID, project name, or requested to inspect past tool outputs, analyze errors, diagnose failure root causes, and propose/test fixes.
allowed-tools: "*"
---

# Session Debugger (Отладка Сессий Johnston)

Инструкция для отладки сессий Johnston, поиска ошибок в логах тулов и устранения их причин.

## Алгоритм работы

### 1. Нахождение сессионных файлов

Сессии Johnston хранятся в JSON-файлах на диске:
- **Сессии проекта:** `~/.johnston/projects/<folder_name>_<path_hash>/sessions/`
- **Сессии субагентов:** `~/.johnston/subagents/sessions/`

Поиск по проекту:
1. Найти директорию проекта в `~/.johnston/projects/` (по имени или hash).
2. Прочитать файлы `.json` в папке `sessions/`.
3. Отсортировать сессии по полю `updated_at` (или по timestamp в имени `session_<timestamp>_<hash>.json`), чтобы найти последнюю или запрошенную сессию.

### 2. Извлечение сообщений и вызовов инструментов

Внутри JSON-файла сессии поле `ui_messages` (или `messages`) содержит полную историю:
- Поиск сообщений типа `"type": "tool"` или вызовов в истории сообщений.
- Фильтрация ошибок:
  - `"is_error": true`
  - Поиск строковых ключей: `Error:`, `Exception`, `failed`, `No such file`, `start_line exceeds`.
  - Поиск сбоев форматирования JSON, обрывов длинных ответов или проблем с таймаутами.

### 3. Диагностика Root Cause

При обнаружении ошибки проанализировать:
- **Входные параметры тула** (`target`, `path`, `start_line`, `end_line`, `arguments`).
- **Свойства файла/окружения** (проверить реальный файл на диске, количество строк `\n`, кодировку, наличие переносов).
- **Типичные проблемы:**
  - Однострочный JSON/лог -> падение `start_line` при `total_lines=1`.
  - Обрезанный вывод с троеточием `...` -> попадание точек в аргументы пути.
  - Потеря pre-fill токенов / `thinking` инжекции в ChatML.

### 4. Предложение решения и исправление

1. Сформулировать четкую причину проблемы (Root Cause).
2. Разработать системный фикс (не затыкание симптомов, а устранение первопричины).
3. Внести изменения в код с сохранением логики и обратной совместимости.
4. Выполнить проверку и запустить юнит-тесты (`uv run pytest`).
