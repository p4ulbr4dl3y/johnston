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
- **Rule Name**: Derived from the filename without extension for rule files, or full relative filename for instruction files.
- **Length Truncation**: Repository instruction files from workspace root are bounded by `llm.agent_md_max_chars` (default 20,000 chars); `.johnston/rules/*.md` are loaded in full.
- **Instruction Files as Rules**: Repository instruction files (such as `AGENTS.md`, `CLAUDE.md`, `.cursorrules`) are automatically injected as project rules with `source="project"` (e.g. `<rule id="project:AGENTS.md">`).

## System Prompt Injection
Active rules are rendered into the system prompt inside the `<user_rules>` block with project priority overriding global rules:
```xml
<user_rules>
User rules. Higher-priority rules appear FIRST and override lower-priority rules on conflict. Order: project > global > defaults.
<rule id="project:AGENTS.md">
Repository guidelines and instructions...
</rule>
<rule id="project:python-style">
Always use `uv` instead of `pip`.
</rule>
<rule id="global:git">
Conventional commits only.
</rule>
</user_rules>
```

## CLI Listing
- List active rules and instruction files: `johnston rules`
- Output structured JSON: `johnston rules --json`