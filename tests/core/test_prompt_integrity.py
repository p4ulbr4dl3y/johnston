"""Automated integrity tests for assembled system prompts and snippets."""

from __future__ import annotations

import re

import pytest

from core.application.generation.prompt_builder import PromptBuilder
from core.domain.defaults.prompts import (
    CODEBASE_NAVIGATION_SNIPPET,
    DEFAULT_SYSTEM_PROMPT,
    HEADLESS_DEFAULT_SYSTEM_PROMPT,
    SUBAGENT_DEFAULT_SYSTEM_PROMPT,
    TOOL_OUTPUT_FORMAT_SNIPPET,
)
from core.domain.policies.role_policy import AgentMode


def _strip_markdown_code(text: str) -> str:
    """Strip fenced code blocks and inline code spans to isolate raw XML tags."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    return re.sub(r"`[^`]*`", "", text)


@pytest.mark.parametrize(
    ("config_name", "base_prompt", "role", "is_subagent", "worktree", "mode"),
    [
        ("main_worker", DEFAULT_SYSTEM_PROMPT, "worker", False, None, AgentMode.INTERACTIVE),
        ("main_explorer", DEFAULT_SYSTEM_PROMPT, "explorer", False, "worktree-branch", AgentMode.INTERACTIVE),
        ("main_reviewer", DEFAULT_SYSTEM_PROMPT, "reviewer", False, None, AgentMode.INTERACTIVE),
        ("subagent_worker", SUBAGENT_DEFAULT_SYSTEM_PROMPT, "worker", True, "sub-branch", AgentMode.SUBAGENT),
        ("headless_worker", HEADLESS_DEFAULT_SYSTEM_PROMPT, "worker", False, None, AgentMode.HEADLESS),
    ],
)
def test_system_prompt_snippets_and_tag_integrity(
    config_name: str,
    base_prompt: str,
    role: str,
    is_subagent: bool,
    worktree: str | None,
    mode: AgentMode,
) -> None:
    builder = PromptBuilder(
        base_system_prompt=base_prompt,
        base_tools=[],
        role=role,
        is_subagent=is_subagent,
        worktree_branch=worktree,
        mode=mode,
        model_name="claude-3-7-sonnet",
    )
    prompt = builder.build_system_prompt()

    # 1. Zero unexpanded template placeholders
    unexpanded = re.findall(r"\{[a-zA-Z0-9_]+\}", prompt)
    assert not unexpanded, f"Found unexpanded placeholders in {config_name}: {unexpanded}"

    # 2. Mandatory shared snippets presence
    assert TOOL_OUTPUT_FORMAT_SNIPPET in prompt, f"Missing TOOL_OUTPUT_FORMAT_SNIPPET in {config_name}"
    assert CODEBASE_NAVIGATION_SNIPPET in prompt, f"Missing CODEBASE_NAVIGATION_SNIPPET in {config_name}"
    assert "<environment>" in prompt and "</environment>" in prompt

    if worktree:
        assert f"- Branch: `{worktree}`" in prompt
        assert "<worktree>" in prompt and "</worktree>" in prompt

    if mode.is_interactive:
        assert f'<role name="{role}"' in prompt
        assert "<subagents>" in prompt and "</subagents>" in prompt
    else:
        assert "<subagents>" not in prompt

    # 3. XML tags balance outside markdown code spans
    cleaned = _strip_markdown_code(prompt)
    tracked_tags = [
        "identity",
        "contract",
        "tool_io",
        "context",
        "hard_limits",
        "report_format",
        "persistence",
        "tool_io_reference",
        "codebase_navigation",
        "user_rules",
        "rule",
        "skills",
        "subagents",
        "role",
        "worktree",
        "environment",
    ]
    for tag in tracked_tags:
        opens = len(re.findall(rf"<{tag}(?:\s+[^>]*)?>", cleaned))
        closes = len(re.findall(rf"</{tag}>", cleaned))
        assert opens == closes, f"Tag <{tag}> mismatch in {config_name}: {opens} opened vs {closes} closed"


@pytest.mark.asyncio
async def test_async_and_sync_system_prompt_consistency() -> None:
    builder = PromptBuilder(
        base_system_prompt=DEFAULT_SYSTEM_PROMPT,
        base_tools=[],
        role="worker",
        model_name="claude-3-7-sonnet",
    )
    # Prime git info cache so both sync and async have identical volatile git state
    async_prompt = await builder.build_system_prompt_async()
    sync_prompt = builder.build_system_prompt()
    assert sync_prompt == async_prompt
