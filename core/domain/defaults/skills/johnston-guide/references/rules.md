# Rules & Directives Reference

## Locations
- Global rules: `~/.johnston/rules/<name>.md`
- Project rules: `.johnston/rules/<name>.md`
- Repository rules (auto-loaded from repo root): `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`, `CONVENTIONS.md`.

## Format
Plain Markdown files. If a top `# Rule Name` heading is present, it is used as the rule name; otherwise, the filename without extension is used.

```markdown
# Python Style
Always run uv instead of pip.
```