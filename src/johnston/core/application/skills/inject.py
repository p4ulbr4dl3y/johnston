"""Skill resolution and injection helpers for prompt augmentation."""
from __future__ import annotations

import os
from typing import Any, List, Optional, Sequence, Tuple

CYRILLIC_HOMOGLYPHS = {
    "а": "a",
    "с": "c",
    "е": "e",
    "о": "o",
    "р": "p",
    "х": "x",
    "у": "y",
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
}


def normalize_homoglyphs(text: str) -> str:
    """Normalize Cyrillic homoglyphs to Latin ASCII equivalents."""
    return "".join(CYRILLIC_HOMOGLYPHS.get(c, c) for c in text)


def resolve_skills(sm: Any, norm_skill_words: Sequence[str]) -> Tuple[List[Any], List[str]]:
    """(sync, thread-safe) Resolve skill names into Skill objects; returns (skills, unresolved)."""
    loaded_skills: List[Any] = []
    unresolved: List[str] = []
    for norm in norm_skill_words:
        skill = sm.get_skill(norm)
        if skill:
            if skill not in loaded_skills:
                loaded_skills.append(skill)
        else:
            unresolved.append(norm)
    return loaded_skills, unresolved


def load_skill_blocks(loaded_skills: Sequence[Any]) -> List[str]:
    """(sync, thread-safe) Read skill content from disk for the invocation blocks."""
    blocks: List[str] = []
    for s in loaded_skills:
        content = getattr(s, "content", "").strip()
        location = getattr(s, "location", None)
        if not content and location and os.path.exists(location):
            try:
                with open(location, "r", encoding="utf-8") as f:
                    raw_c = f.read()
                from johnston.core.infrastructure.runtime.frontmatter import parse_frontmatter

                _, body = parse_frontmatter(raw_c)
                content = body.strip()
            except Exception:
                content = ""
        from johnston.core.infrastructure.runtime.xml_utils import escape_xml_attr

        escaped_name = escape_xml_attr(getattr(s, "name", "") or "")
        path_attr = f' path="{escape_xml_attr(location)}"' if location else ""
        blocks.append(f'<skill name="{escaped_name}"{path_attr}>\n{content}\n</skill>')
    return blocks


def extract_and_inject_skills(
    prompt: str,
    extra_skills: Optional[Sequence[str]] = None,
    sm: Any = None,
) -> Tuple[str, List[str]]:
    """Extract /skill slash tokens or extra skill names, inject XML blocks, and return (augmented_prompt, loaded_names)."""
    if not prompt and not extra_skills:
        return (prompt or ""), []

    if sm is None:
        from johnston.core.application.skills.manager import get_skill_manager

        sm = get_skill_manager()

    words = prompt.strip().split() if prompt else []
    loaded_skills: List[Any] = []
    other_words: List[str] = []

    for w in words:
        if w.startswith("/"):
            raw_name = w[1:].lower()
            norm = normalize_homoglyphs(raw_name)
            skill = sm.get_skill(norm)
            if skill:
                if skill not in loaded_skills:
                    loaded_skills.append(skill)
                continue
        other_words.append(w)

    if extra_skills:
        for s in extra_skills:
            if s and s.strip():
                clean_s = s.strip().lstrip("/").lower()
                norm = normalize_homoglyphs(clean_s)
                skill = sm.get_skill(norm)
                if skill and skill not in loaded_skills:
                    loaded_skills.append(skill)

    if not loaded_skills:
        return prompt, []

    skill_blocks = load_skill_blocks(loaded_skills)
    skills_content = "\n\n".join(skill_blocks)
    user_request = " ".join(other_words).strip()

    augmented = f"{skills_content}\n\n{user_request}" if user_request else skills_content
    loaded_names = [getattr(s, "name", "") for s in loaded_skills if getattr(s, "name", "")]

    return augmented, loaded_names
