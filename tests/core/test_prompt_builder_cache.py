"""Stable-core caching semantics for PromptBuilder.

Covers the cache-first assembly introduced by the perf offload: sync/async
builder equivalence, invalidation when a role file's content changes, and the
cache-hit path that must not resolve the role definition from disk again.
"""
import os

import pytest

import core.application.generation.prompt_builder as pb
from core.application.generation.prompt_builder import PromptBuilder
from core.role_registry import RoleRegistry

_CUSTOM_ROLE_MD = """---
key: custom
name: Custom
description: Custom test role
---
{body}
"""


def _write_role(project_dir: str, body: str) -> None:
    """Create/overwrite a custom role definition in the project roles dir."""
    roles_dir = os.path.join(project_dir, ".johnston", "roles")
    os.makedirs(roles_dir, exist_ok=True)
    with open(os.path.join(roles_dir, "custom.md"), "w", encoding="utf-8") as f:
        f.write(_CUSTOM_ROLE_MD.format(body=body))


@pytest.fixture(autouse=True)
def _isolated_caches():
    """Keep the module-level prompt caches and the RoleRegistry singleton
    (both process-global) isolated between tests."""
    pb._STABLE_CORE_CACHE.clear()
    pb._PROJECT_INSTRUCTION_CACHE.clear()
    registry = RoleRegistry.get_instance()
    yield
    pb._STABLE_CORE_CACHE.clear()
    registry.invalidate_cache()
    registry.current_project_dir = None
    registry.load_roles(project_dir=os.getcwd())  # restore default-dir roles


def _make_builder(project_dir: str, role: str = "custom", **kwargs) -> PromptBuilder:
    return PromptBuilder(
        "Base prompt for cache tests",
        [],
        role=role,
        cwd=project_dir,
        sandbox_enabled=False,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_async_builder_matches_sync_builder(tmp_path):
    """The async builder must produce byte-identical prompts to the sync one
    (all worker-thread offloads must not change the assembled output)."""
    project = str(tmp_path)
    _write_role(project, "<rules>\nUse async discipline.\n</rules>")

    sync_prompt = _make_builder(project).build_system_prompt()
    async_prompt = await _make_builder(project).build_system_prompt_async()

    assert sync_prompt == async_prompt
    assert '<role name="custom"' in async_prompt
    assert "Use async discipline." in async_prompt


@pytest.mark.asyncio
async def test_async_subagent_worktree_matches_sync(tmp_path):
    """Subagent + worktree path (role block excluded, worktree block included)
    must also be identical between the sync and async builders."""
    project = str(tmp_path)
    _write_role(project, "<rules>\nSubagent rules.\n</rules>")

    kwargs = {"role": "worker", "is_subagent": True, "worktree_branch": "feature-x"}
    sync_prompt = _make_builder(project, **kwargs).build_system_prompt()
    async_prompt = await _make_builder(project, **kwargs).build_system_prompt_async()

    assert sync_prompt == async_prompt
    assert "<worktree>" in async_prompt
    assert "Branch: `feature-x`" in async_prompt
    assert '<role name="custom"' not in async_prompt


def test_stable_core_invalidated_when_role_file_changes(tmp_path):
    """A role definition edit on disk must invalidate the cached stable core,
    so the next build reflects the new role prompt."""
    project = str(tmp_path)
    _write_role(project, "<rules>\nVersion one rule.\n</rules>")

    builder = _make_builder(project)
    p1 = builder.build_system_prompt()
    assert "Version one rule." in p1

    # Role file changes on disk; force the registry to re-scan on the next turn.
    _write_role(project, "<rules>\nVersion two rule.\n</rules>")
    RoleRegistry.get_instance().invalidate_cache()

    p2 = builder.build_system_prompt()
    assert "Version two rule." in p2
    assert "Version one rule." not in p2


def test_stable_core_hit_skips_role_resolution(tmp_path, monkeypatch):
    """Cache-hit turns must not resolve the role definition from disk again:
    the registry lookup is only needed on the miss path."""
    project = str(tmp_path)
    _write_role(project, "<rules>\nStable rule.\n</rules>")

    calls = []
    original_get_role = RoleRegistry.get_role

    def _spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return original_get_role(self, *args, **kwargs)

    monkeypatch.setattr(RoleRegistry, "get_role", _spy)

    _make_builder(project).build_system_prompt()
    assert calls  # first build resolves the role once (cache miss)
    n_after_miss = len(calls)

    # Second build with identical inputs hits the stable core without any
    # further role resolution.
    _make_builder(project).build_system_prompt()
    assert len(calls) == n_after_miss
