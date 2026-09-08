"""Unit tests for core/application/skills/inject.py."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from johnston_core.application.skills.inject import (
    extract_and_inject_skills,
    load_skill_blocks,
    normalize_homoglyphs,
    resolve_skills,
)


class TestSkillInject(unittest.TestCase):
    """Test suite for skill resolution, loading, and injection."""

    def test_normalize_homoglyphs(self):
        # Cyrillic 'с', 'а', 'е', 'о' -> Latin 'c', 'a', 'e', 'o'
        cyrillic_caveman = "саveman"
        normalized = normalize_homoglyphs(cyrillic_caveman)
        self.assertEqual(normalized, "caveman")
        self.assertEqual(normalize_homoglyphs("hello"), "hello")

    def test_resolve_skills(self):
        sm = MagicMock()
        skill_a = MagicMock(name="skill_a")
        skill_a.name = "skill_a"
        sm.get_skill.side_effect = lambda name: skill_a if name == "skill_a" else None

        loaded, unresolved = resolve_skills(sm, ["skill_a", "skill_b", "skill_a"])
        self.assertEqual(loaded, [skill_a])
        self.assertEqual(unresolved, ["skill_b"])

    def test_load_skill_blocks(self):
        skill1 = MagicMock(name="skill1")
        skill1.name = "caveman"
        skill1.location = "/path/to/skill/SKILL.md"
        skill1.content = "Be brief."

        blocks = load_skill_blocks([skill1])
        self.assertEqual(len(blocks), 1)
        self.assertIn('<skill name="caveman" path="/path/to/skill/SKILL.md">', blocks[0])
        self.assertIn("Be brief.", blocks[0])
        self.assertTrue(blocks[0].endswith("</skill>"))

    def test_extract_and_inject_skills_empty(self):
        prompt, loaded = extract_and_inject_skills("")
        self.assertEqual(prompt, "")
        self.assertEqual(loaded, [])

        prompt, loaded = extract_and_inject_skills(None)
        self.assertEqual(prompt, "")
        self.assertEqual(loaded, [])

    def test_extract_and_inject_skills_no_skills_present(self):
        sm = MagicMock()
        sm.get_skill.return_value = None

        prompt = "regular prompt without skills /unknown"
        res_prompt, loaded = extract_and_inject_skills(prompt, sm=sm)
        self.assertEqual(res_prompt, prompt)
        self.assertEqual(loaded, [])

    def test_extract_and_inject_skills_slash_command(self):
        sm = MagicMock()
        skill = MagicMock()
        skill.name = "caveman"
        skill.location = None
        skill.content = "Short answers only."

        def get_skill(name):
            return skill if name == "caveman" else None

        sm.get_skill.side_effect = get_skill

        prompt = "/caveman review the code in /var/log"
        augmented, loaded = extract_and_inject_skills(prompt, sm=sm)

        self.assertEqual(loaded, ["caveman"])
        self.assertIn('<skill name="caveman">', augmented)
        self.assertIn("Short answers only.", augmented)
        # Verify /var/log remained in its position in the prompt
        self.assertIn("review the code in /var/log", augmented)
        self.assertNotIn("/caveman", augmented.split("</skill>\n\n")[-1])

    def test_extract_and_inject_skills_extra_skills(self):
        sm = MagicMock()
        skill = MagicMock()
        skill.name = "debugger"
        skill.location = None
        skill.content = "Debug thoroughly."
        sm.get_skill.side_effect = lambda n: skill if n == "debugger" else None

        prompt = "fix issue"
        augmented, loaded = extract_and_inject_skills(prompt, extra_skills=["debugger"], sm=sm)

        self.assertEqual(loaded, ["debugger"])
        self.assertIn('<skill name="debugger">', augmented)
        self.assertIn("fix issue", augmented)

    def test_extract_and_inject_skills_no_prompt_text_only_skills(self):
        sm = MagicMock()
        skill = MagicMock()
        skill.name = "summary"
        skill.location = None
        skill.content = "Summary instructions."
        sm.get_skill.return_value = skill

        augmented, loaded = extract_and_inject_skills("/summary", sm=sm)
        self.assertEqual(loaded, ["summary"])
        self.assertIn('<skill name="summary">', augmented)
        # No extra trailing newlines or empty text
        self.assertTrue(augmented.endswith("</skill>"))
