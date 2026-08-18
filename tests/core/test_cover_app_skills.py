"""Coverage-focused unit tests for core/application/skills/manager.py.

Covers error/edge paths in _provision_skill, signature caching, _scan_skills,
toggle_hidden and the system-prompt snippet builder that test_skill_manager.py
does not exercise. File-system only, no network calls.
"""

import os
import time
from unittest.mock import patch

import pytest

from core.application.skills.manager import Skill, SkillManager, SkillScope
from core.domain.defaults.skills.loader import get_bundled_skill


def _write_skill(dir_path, rel_dir, name_hint, frontmatter_lines, body="Body text."):
    """Create a SKILL.md at dir_path/<rel_dir>/SKILL.md from frontmatter lines."""
    skill_dir = os.path.join(dir_path, rel_dir)
    os.makedirs(skill_dir, exist_ok=True)
    fm = "\n".join(frontmatter_lines)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\n{fm}\n---\n{body}")
    return skill_dir


class _SkillManagerHarness:
    """Hand-rolled SkillManager pointed at temp dirs, bypassing class globals."""

    def __init__(self, tmp_path):
        global_dir = str(tmp_path / "global")
        project_dir = str(tmp_path / "proj")
        self.sm = SkillManager.__new__(SkillManager)
        self.sm.project_dir = project_dir
        self.sm.global_dir = global_dir
        self.sm.project_dir_skills = os.path.join(project_dir, ".johnston", "skills")
        self.sm._scan_signature = None
        self.sm._scan_cache = None
        self.sm._scan_ts = 0.0
        self.global_dir = global_dir


@pytest.fixture
def harness(tmp_path):
    return _SkillManagerHarness(tmp_path)


def test_provision_skill_write_error_is_swallowed(harness):
    skill = get_bundled_skill("init")

    def boom(path, content):
        raise OSError("disk full")

    harness.sm._provision_skill(skill, boom)
    # Any files that raised simply get logged; no exception propagates.
    assert skill.files  # sanity: bundled skill has files to attempt


def test_list_skills_reuses_cache_when_signature_unchanged(harness):
    sm = harness.sm
    skill = Skill(
        name="s", description="d", location="loc", content="c", scope=SkillScope.GLOBAL, hidden=False
    )
    sm._scan_cache = [skill]
    sm._scan_signature = ("sig",)
    sm._scan_ts = time.time() - 100.0  # TTL expired -> recompute signature
    with patch.object(sm, "_compute_scan_signature", return_value=("sig",)):
        result = sm.list_skills()
    assert result == [skill]
    assert sm._scan_ts >= time.time() - 1.0  # timestamp refreshed


def test_scan_skills_handles_stat_oserror(harness):
    sm = harness.sm
    _write_skill(sm.global_dir, "my-skill", None, ["description: a skill"])
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        if str(path).endswith("SKILL.md"):
            raise OSError("gone")
        return real_stat(path, *args, **kwargs)

    with patch.object(os, "stat", side_effect=fake_stat):
        skills, sig = sm._scan_skills()
    assert [s.name for s in skills] == ["my-skill"]
    assert sig == ()


def test_scan_skills_skips_unreadable_skill_file(harness):
    sm = harness.sm
    skill_dir = _write_skill(sm.global_dir, "bad-skill", None, ["description: x"])
    target = os.path.join(skill_dir, "SKILL.md")
    real_open = open

    def fake_open(path, *args, **kwargs):
        if path == target:
            raise OSError("unreadable")
        return real_open(path, *args, **kwargs)

    with patch("builtins.open", side_effect=fake_open):
        skills, _ = sm._scan_skills()
    assert skills == []


def test_scan_skills_name_fallback_from_dirname(harness):
    sm = harness.sm
    _write_skill(sm.global_dir, "codex-skill", None, ["description: no name key"])
    skills, _ = sm._scan_skills()
    assert [s.name for s in skills] == ["codex-skill"]


def test_scan_skills_skips_dot_hidden_skill_dir(harness):
    sm = harness.sm
    _write_skill(sm.global_dir, ".hidden-skill", None, ["description: should be skipped"])
    skills, _ = sm._scan_skills()
    assert skills == []


def test_scan_skills_skips_dotname_skill(harness):
    sm = harness.sm
    # Name directly from frontmatter starting with '.' must be skipped too.
    _write_skill(sm.global_dir, "dotname-skill", None, ["name: .dotname", "description: x"])
    skills, _ = sm._scan_skills()
    assert skills == []


def test_scan_skills_derives_description_from_body(harness):
    sm = harness.sm
    _write_skill(sm.global_dir, "desc-skill", None, ["name: desc-skill"], "# Heading\n\nUseful description\nmore")
    skills, _ = sm._scan_skills()
    s = next(x for x in skills if x.name == "desc-skill")
    assert s.description == "Useful description"
    assert s.content == "# Heading\n\nUseful description\nmore"


def test_toggle_hidden_missing_skill_returns_false(harness):
    assert harness.sm.toggle_hidden("nonexistent") is False


def test_toggle_hidden_updates_user_invocable(harness):
    sm = harness.sm
    skill_dir = _write_skill(
        sm.global_dir,
        "invoc",
        None,
        ["name: invoc", "description: d", "hidden: true", "user_invocable: true"],
    )
    target = os.path.join(skill_dir, "SKILL.md")
    result = sm.toggle_hidden("invoc")
    assert result is False  # was hidden -> now visible
    with open(target, encoding="utf-8") as f:
        content = f.read()
    assert "hidden: false" in content
    assert "user_invocable: true" in content  # user_invocable mirrors the new visible state


def test_toggle_hidden_appends_hidden_when_not_present(harness):
    sm = harness.sm
    skill_dir = _write_skill(sm.global_dir, "nohidden", None, ["name: nohidden", "description: d"])
    target = os.path.join(skill_dir, "SKILL.md")
    result = sm.toggle_hidden("nohidden")
    assert result is True  # was visible -> now hidden
    with open(target, encoding="utf-8") as f:
        assert "hidden: true" in f.read()


def test_toggle_hidden_truncated_frontmatter(harness):
    sm = harness.sm
    skill_dir = os.path.join(sm.global_dir, "truncated")
    os.makedirs(skill_dir, exist_ok=True)
    target = os.path.join(skill_dir, "SKILL.md")
    with open(target, "w", encoding="utf-8") as f:
        f.write("---\nname: truncated")  # only one '---' -> len(parts) < 3
    assert sm.toggle_hidden("truncated") is True
    with open(target, encoding="utf-8") as f:
        assert f.read().startswith("---\nhidden: true")


def test_toggle_hidden_no_frontmatter(harness):
    sm = harness.sm
    skill_dir = os.path.join(sm.global_dir, "plain")
    os.makedirs(skill_dir, exist_ok=True)
    target = os.path.join(skill_dir, "SKILL.md")
    with open(target, "w", encoding="utf-8") as f:
        f.write("just some plain markdown")
    assert sm.toggle_hidden("plain") is True
    with open(target, encoding="utf-8") as f:
        assert f.read().startswith("---\nhidden: true\n---")


def test_toggle_hidden_write_error_returns_previous_state(harness):
    sm = harness.sm
    _write_skill(sm.global_dir, "errorskill", None, ["name: errorskill", "description: d", "hidden: true"])
    with patch(
        "core.infrastructure.platform.platform_utils.atomic_write_text", side_effect=OSError("nope")
    ):
        # toggle on true hidden -> new_hidden False; save fails -> returns old hidden True.
        assert sm.toggle_hidden("errorskill") is True


def test_system_prompt_snippet_empty(harness):
    with patch.object(harness.sm, "list_skills", return_value=[]):
        assert harness.sm.get_system_prompt_snippet() == ""


def test_system_prompt_snippet_global_and_project(harness):
    global_skill = Skill(
        name="glob",
        description="Global desc",
        location="g",
        content="",
        scope=SkillScope.GLOBAL,
        hidden=False,
    )
    project_skill = Skill(
        name="proj",
        description="",
        location="p",
        content="",
        scope=SkillScope.PROJECT,
        hidden=False,
    )
    with patch.object(harness.sm, "list_skills", return_value=[global_skill, project_skill]):
        snippet = harness.sm.get_system_prompt_snippet()
    assert "- `glob`: Global desc" in snippet
    assert "- `proj`" in snippet
    assert "### Global" in snippet
    assert "### Project" in snippet
