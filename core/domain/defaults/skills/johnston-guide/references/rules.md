# Rules & Directives Reference

## Locations
- Global rules: `~/.johnston/rules/<name>.md` (or `.markdown`)
- Project rules: `.johnston/rules/<name>.md` (or `.markdown`)
- Repository instruction files (auto-loaded from repo root):
  - `AGENTS.md`, `AGENT.md`
  - `CLAUDE.md`
  - `.cursorrules`, `.cursor/rules/*.mdc`, `.cursor/rules/*.md`
  - `.windsurfrules`
  - `.clinerules`
  - `CONVENTIONS.md`
  - `.github/copilot-instructions.md`

## Format & Parsing
- Rule files are Markdown files with optional YAML frontmatter.
- **Rule Name**: Always derived from the filename without extension (headings inside Markdown are not used as rule names).
- **Length Truncation**: Repository instruction files from workspace root are bounded by `llm.agent_md_max_chars` (default 20,000 chars); `.johnston/rules/*.md` are loaded in full.

## System Prompt Injection
Active rules are rendered into the system prompt inside the `<user_rules>` block with project priority overriding global rules:
```xml
<user_rules>
User rules. Higher-priority rules appear FIRST and override lower-priority rules on conflict. Order: project > global > defaults.
<rule id="project:python-style">
Always use `uv` instead of `pip`.
</rule>
</user_rules>
```