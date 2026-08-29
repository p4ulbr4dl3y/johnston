# Rules & Directives Reference

## Locations
- Global rules: `~/.johnston/rules/<name>.md`
- Project rules: `.johnston/rules/<name>.md`
- Repository rules (auto-loaded from repo root):
  - `AGENTS.md`, `AGENT.md` (Universal/OpenAI/Codex)
  - `CLAUDE.md` (Claude Code)
  - `.cursorrules`, `.cursor/rules/*.mdc`, `.cursor/rules/*.md` (Cursor)
  - `.windsurfrules` (Windsurf)
  - `.clinerules` (Cline / Roo Code)
  - `CONVENTIONS.md` (Aider / standard)
  - `.github/copilot-instructions.md` (GitHub Copilot)

## Format
Plain Markdown files. If a top `# Rule Name` heading is present, it is used as the rule name; otherwise, the filename without extension is used.

```markdown
# Python Style
Always run uv instead of pip.
```