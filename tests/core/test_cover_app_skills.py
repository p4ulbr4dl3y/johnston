"""Coverage-focused unit tests for core/application/skills/manager.py.

Covers error/edge paths in _provision_skill, signature caching, _scan_skills,
toggle_hidden and the system-prompt snippet builder that test_skill_manager.py
does not exercise. File-system only, no network calls.
"""

import os
import time
from unittest.mock import patch

import pytest

from core.application.skills.manager import (
    Skill,
    SkillManager,
    SkillScope,
)
from core.domain.defaults.skills.loader import load_bundled_skills
from core.infrastructure.config.settings import get_settings


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
        self.sm.include_bundled = False
        self.sm._scan_signature = None
        self.sm._scan_cache = None
        self.sm._scan_ts = 0.0
        self.global_dir = global_dir


@pytest.fixture
def harness(tmp_path):
    return _SkillManagerHarness(tmp_path)


def test_load_bundled_skills_returns_bundled_scope():
    bundled = load_bundled_skills()
    assert len(bundled) > 0
    for s in bundled:
        assert s.scope == SkillScope.BUNDLED
        assert s.name


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


def test_toggle_hidden_missing_skill_raises_key_error(harness):
    with pytest.raises(KeyError):
        harness.sm.toggle_hidden("nonexistent")


def test_toggle_hidden_updates_settings_without_modifying_file(harness):
    sm = harness.sm
    skill_dir = _write_skill(
        sm.global_dir,
        "invoc",
        None,
        ["name: invoc", "description: d", "hidden: true"],
    )
    target = os.path.join(skill_dir, "SKILL.md")
    before_content = open(target, encoding="utf-8").read()

    result = sm.toggle_hidden("invoc")
    assert result is False  # was hidden -> now visible
    # File on disk must NOT be modified
    assert open(target, encoding="utf-8").read() == before_content
    assert get_settings().skills.hidden.get("invoc") is False

    # Toggle back to hidden
    result2 = sm.toggle_hidden("invoc")
    assert result2 is True
    assert open(target, encoding="utf-8").read() == before_content
    assert get_settings().skills.hidden.get("invoc") is True


def test_toggle_hidden_error_in_settings_raises(harness):
    sm = harness.sm
    _write_skill(sm.global_dir, "errorskill", None, ["name: errorskill", "description: d"])
    with patch("core.application.skills.manager.patch_settings", side_effect=RuntimeError("settings save error")):
        with pytest.raises(RuntimeError):
            sm.toggle_hidden("errorskill")


def test_system_prompt_skills_empty(harness):
    with patch.object(harness.sm, "list_skills", return_value=[]):
        assert harness.sm.get_system_prompt_skills() == []


def test_system_prompt_skills_global_and_project(harness):
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
        skills = harness.sm.get_system_prompt_skills()
    assert len(skills) == 2
    assert skills[0].name == "glob"
    assert skills[1].name == "proj"
