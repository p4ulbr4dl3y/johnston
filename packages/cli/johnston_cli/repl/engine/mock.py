"""Synthetic / mock execution engine for zero-cost testing and UI iteration."""
from __future__ import annotations

import asyncio
import random
from typing import AsyncIterator

from johnston_cli.repl.engine.events import (
    ReplEvent,
    TextChunkEvent,
    ThinkingDoneEvent,
    ThinkingStartEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    TurnDoneEvent,
)
from johnston_cli.repl.session import ReplSession


class MockEngine:
    """Synthetic engine simulating model reasoning, tool usage, and token streaming."""

    def __init__(self, fast: bool = False) -> None:
        self.fast = fast

    async def _sleep(self, seconds: float) -> None:
        if not self.fast and seconds > 0:
            await asyncio.sleep(seconds)

    async def generate(
        self,
        prompt: str,
        session: ReplSession,
    ) -> AsyncIterator[ReplEvent]:
        prompt_lower = prompt.lower().strip()

        # 1. Thinking phase
        yield ThinkingStartEvent()
        thinking_duration = 0.1 if self.fast else round(random.uniform(1.1, 2.3), 2)
        await self._sleep(thinking_duration)
        thinking_tokens = random.randint(180, 450)
        thinking_text = (
            f"1. Анализирую запрос: \"{prompt}\"\n"
            "2. Оцениваю контекст проекта, файлы и инструменты\n"
            "3. Формирую последовательность вызовов инструментов"
        )
        yield ThinkingDoneEvent(
            duration_s=thinking_duration,
            token_count=thinking_tokens,
            content=thinking_text,
        )

        # 2. Tool calls simulation
        if any(k in prompt_lower for k in ("test", "pytest", "run", "bash", "shell", "провер")):
            yield ToolCallStartEvent(
                tool_name="Shell",
                tool_args={"command": "uv run pytest -k test_auth"},
            )
            await self._sleep(0.6)
            yield ToolCallResultEvent(
                tool_name="Shell",
                target="uv run pytest -k test_auth",
                summary="================ 3 passed in 0.42s ================",
                exit_code=0,
            )
            response_text = (
                "Все тесты успешно пройдены:\n\n"
                "- `test_auth_valid_token`: PASSED\n"
                "- `test_auth_expired_token`: PASSED\n"
                "- `test_auth_malformed_token`: PASSED\n\n"
                "Регрессий не обнаружено."
            )

        elif any(k in prompt_lower for k in ("fix", "auth", "bug", "почини", "исправ", "edit")):
            yield ToolCallStartEvent(
                tool_name="Read",
                tool_args={"path": "core/auth.py"},
            )
            await self._sleep(0.4)
            yield ToolCallResultEvent(
                tool_name="Read",
                target="core/auth.py",
                summary=(
                    "12: def check_token(token: str) -> bool:\n"
                    "13:     if token.expires < time.time():  # BUG: < instead of <=\n"
                    "14:         return False"
                ),
            )

            diff_content = (
                "--- core/auth.py\n"
                "+++ core/auth.py\n"
                "@@ -13,3 +13,3 @@\n"
                "-    if token.expires < time.time():\n"
                "+    if token.expires <= time.time():"
            )
            yield ToolCallStartEvent(
                tool_name="Edit",
                tool_args={"path": "core/auth.py"},
            )
            await self._sleep(0.5)
            yield ToolCallResultEvent(
                tool_name="Edit",
                target="core/auth.py",
                diff=diff_content,
                summary="Updated line 13",
            )
            response_text = (
                "Проблема была в строгом неравенстве: при точном совпадении таймстемпа токен считался валидным.\n\n"
                "Заменил `<` на `<=` в файле `core/auth.py`."
            )

        else:
            # 1. Read
            yield ToolCallStartEvent(tool_name="Read", tool_args={"path": "AGENTS.md:1-50"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="Read",
                target="AGENTS.md:1-50",
                summary="# Repository Guidelines\nJohnston: Python terminal AI assistant...",
            )

            # 2. Search (expandable)
            yield ToolCallStartEvent(tool_name="Search", tool_args={"query": "check_token"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="Search",
                target='"check_token" in core/',
                summary=(
                    "Found 3 matches:\n"
                    "  core/auth.py:13: def check_token(token: str)\n"
                    "  core/auth.py:45: if check_token(t):\n"
                    "  tests/test_auth.py:10: assert check_token(valid)"
                ),
            )

            # 3. Create (expandable)
            yield ToolCallStartEvent(tool_name="Create", tool_args={"path": "src/utils/token.py"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="Create",
                target="src/utils/token.py",
                diff=(
                    "--- /dev/null\n"
                    "+++ src/utils/token.py\n"
                    "@@ -0,0 +1,4 @@\n"
                    "+def validate_timestamp(exp: float) -> bool:\n"
                    "+    import time\n"
                    "+    return exp >= time.time()"
                ),
            )

            # 4. Edit (expandable)
            diff_content = (
                "--- core/auth.py\n"
                "+++ core/auth.py\n"
                "@@ -13,3 +13,3 @@\n"
                "-    if token.expires < time.time():\n"
                "+    if token.expires <= time.time():"
            )
            yield ToolCallStartEvent(tool_name="Edit", tool_args={"path": "core/auth.py"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="Edit",
                target="core/auth.py",
                diff=diff_content,
                summary="Updated line 13",
            )

            # 5. Shell (expandable)
            yield ToolCallStartEvent(tool_name="Shell", tool_args={"command": "uv run pytest -k test_auth"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="Shell",
                target="uv run pytest -k test_auth",
                summary="================ 3 passed in 0.42s ================",
                exit_code=0,
            )

            # 6. WebFetch
            yield ToolCallStartEvent(tool_name="WebFetch", tool_args={"url": "https://docs.astral.sh/uv/"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="WebFetch",
                target="https://docs.astral.sh/uv/",
                summary="HTTP 200 (14.2 KB)",
            )

            # 7. InvokeSubagent
            yield ToolCallStartEvent(tool_name="InvokeSubagent", tool_args={"role": "Researcher"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="InvokeSubagent",
                target='Researcher: "Find token RFC"',
                summary="Started subagent-42",
            )

            # 8. MessageSubagent
            yield ToolCallStartEvent(tool_name="MessageSubagent", tool_args={"id": "subagent-42"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="MessageSubagent",
                target='to subagent-42: "Check expires_at"',
                summary="Message delivered",
            )

            # 9. AskUser
            yield ToolCallStartEvent(tool_name="AskUser", tool_args={"question": "Deprecate old tokens?"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="AskUser",
                target='"Should we deprecate older token versions?"',
                summary="Response: No",
            )

            # 10. Kill
            yield ToolCallStartEvent(tool_name="Kill", tool_args={"id": "subagent-42"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="Kill",
                target="subagent-42",
                summary="Terminated subagent-42",
            )

            # 11. UpdatePlan (expandable, last item with hint)
            yield ToolCallStartEvent(tool_name="UpdatePlan", tool_args={"step": "Implement auth check"})
            await self._sleep(0.1)
            yield ToolCallResultEvent(
                tool_name="UpdatePlan",
                target="2/4: Implement auth check",
                summary=(
                    "[x] 1. Проанализировать архитектуру\n"
                    "[x] 2. Реализовать валидацию токена\n"
                    "[>] 3. Запустить тесты\n"
                    "[ ] 4. Зафиксировать изменения"
                ),
            )

            response_text = (
                f"Получил запрос: \"{prompt}\".\n\n"
                "Смоделированы все 11 инструментов Johnston:\n\n"
                "**Свернутые (1 строка)**:\n"
                "- `Read`, `WebFetch`, `InvokeSubagent`, `MessageSubagent`, `AskUser`, `Kill`\n\n"
                "**Раскрывающиеся по Ctrl+O**:\n"
                "- `Search` (список совпадений)\n"
                "- `Create` (дифф нового файла)\n"
                "- `Edit` (дифф изменений)\n"
                "- `Shell` (вывод команды)\n"
                "- `UpdatePlan` (чеклист плана)\n\n"
                "Нажмите **Ctrl+O**, чтобы раскрыть / скрыть детали."
            )

        # 3. Stream text chunks with realistic cadence
        words = response_text.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield TextChunkEvent(text=chunk)
            await self._sleep(random.uniform(0.015, 0.035))

        # 4. Turn completion metrics
        added_tokens = thinking_tokens + len(response_text) // 3
        estimated_cost = round(added_tokens * 0.000003, 4)
        yield TurnDoneEvent(
            total_tokens=session.total_tokens + added_tokens,
            added_tokens=added_tokens,
            estimated_cost_usd=estimated_cost,
        )
