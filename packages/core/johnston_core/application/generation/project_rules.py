"""Project rules and instruction file loading with mtime-based cache invalidation."""

import asyncio
import os
from typing import Any, List, Tuple

from johnston_core.domain.defaults.config import DEFAULT_AGENT_MD_MAX_CHARS
from johnston_core.infrastructure.runtime.lru import LruCache

INSTRUCTION_FILES = [
    "AGENTS.md",
    "AGENT.md",
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    "CONVENTIONS.md",
    os.path.join(".github", "copilot-instructions.md"),
]

_PROJECT_INSTR_CACHE_MAX = 64

# (realpath cwd) -> (mtime/size signature, rules). Invalidates when any
# instruction file appears/disappears or its mtime changes.
_PROJECT_INSTRUCTION_CACHE: "LruCache[str, Tuple[tuple, List[Any]]]" = LruCache(_PROJECT_INSTR_CACHE_MAX)


def _scan_cursor_rules_files(cwd: str) -> List[Tuple[str, str]]:
    """Scan .cursor/rules directory for .md and .mdc files; returns [(rel_path, abs_path), ...]"""
    cursor_dir = os.path.join(cwd, ".cursor", "rules")
    if not os.path.isdir(cursor_dir):
        return []
    rules = []
    try:
        for fname in sorted(os.listdir(cursor_dir)):
            if fname.endswith((".md", ".mdc")) and not fname.startswith("."):
                fpath = os.path.join(cursor_dir, fname)
                if os.path.isfile(fpath):
                    rules.append((os.path.join(".cursor", "rules", fname), fpath))
    except Exception:
        pass
    return rules


def _project_instr_signature(cwd: str) -> tuple:
    """Cheap (name, mtime_ns, size) signature for every instruction file present.

    Detects additions, removals and edits without re-reading file contents.
    """
    entries = []
    for name in INSTRUCTION_FILES:
        fpath = os.path.join(cwd, name)
        try:
            st = os.stat(fpath)
            entries.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            positions = {e[0] for e in entries}
            if name not in positions:
                entries.append((name, 0, 0))

    for rel_name, fpath in _scan_cursor_rules_files(cwd):
        try:
            st = os.stat(fpath)
            entries.append((rel_name, st.st_mtime_ns, st.st_size))
        except OSError:
            pass

    return tuple(entries)


def get_project_instruction_rules(cwd: str = None) -> List[Any]:
    """Reads INSTRUCTION_FILES and .cursor/rules from a working directory as RuleDefinitions.

    Cached per-directory by an mtime/size signature; files are only re-read
    when they change, so the agent loop does not re-open disk files every turn.
    """
    cwd = os.path.realpath(cwd) if cwd else os.getcwd()
    sig = _project_instr_signature(cwd)
    cached = _PROJECT_INSTRUCTION_CACHE.get(cwd)
    if cached is not None and cached[0] == sig:
        return cached[1]

    from johnston_core.application.rules.rules import RuleDefinition
    from johnston_core.infrastructure.runtime.frontmatter import parse_frontmatter

    try:
        from johnston_core.infrastructure.config.settings import get_settings

        max_chars = get_settings().llm.agent_md_max_chars
    except Exception:
        max_chars = DEFAULT_AGENT_MD_MAX_CHARS

    found_rules = []
    for name in INSTRUCTION_FILES:
        filepath = os.path.join(cwd, name)
        if os.path.isfile(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read().strip()
                if raw:
                    _, content = parse_frontmatter(raw)
                    content = content.strip()
                    if content:
                        if len(content) > max_chars:
                            content = content[:max_chars] + f"\n... [Project instructions truncated at {max_chars} chars]"
                        found_rules.append(RuleDefinition(name=name, content=content, source="project"))
            except Exception:
                pass

    for rel_name, filepath in _scan_cursor_rules_files(cwd):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()
            if raw:
                _, content = parse_frontmatter(raw)
                content = content.strip()
                if content:
                    if len(content) > max_chars:
                        content = content[:max_chars] + f"\n... [Project instructions truncated at {max_chars} chars]"
                    found_rules.append(RuleDefinition(name=rel_name, content=content, source="project"))
        except Exception:
            pass

    _PROJECT_INSTRUCTION_CACHE.put(cwd, (sig, found_rules))
    return found_rules


def get_project_instructions_snippet(cwd: str = None) -> str:
    """Reads INSTRUCTION_FILES from a working directory and formats as rules block."""
    from johnston_core.infrastructure.runtime.prompt_markdown import format_rules_markdown

    rules = get_project_instruction_rules(cwd)
    return format_rules_markdown(rules)


def get_rules_snippet(role: str = "worker", cwd: str = None) -> str:
    """Reads rules from ~/.johnston/rules and <cwd>/.johnston/rules and project instruction files.

    cwd selects the project directory so a subagent working in an isolated
    worktree sees its own rules and instructions instead of the parent checkout's.
    """
    from johnston_core.application.rules.rules import RulesManager
    from johnston_core.infrastructure.runtime.prompt_markdown import format_rules_markdown

    rules = list(RulesManager.get_instance().get_active_rules(project_dir=cwd))
    instructions = get_project_instruction_rules(cwd)
    return format_rules_markdown(rules + instructions)


async def get_rules_snippet_async(role: str = "worker", cwd: str = None) -> str:
    """Async variant of ``get_rules_snippet``: reads rules on a thread."""
    return await asyncio.to_thread(get_rules_snippet, role, cwd)
