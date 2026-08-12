# Rules & Directives Reference

## Locations
- Global rules: `~/.johnston/rules/<name>.md`
- Project rules: `.johnston/rules/<name>.md`
- Repository rules: `AGENTS.md`, `CLAUDE.md`, `.cursorrules` in repository root.

## Frontmatter Format
```markdown
---
name: python_style
role: worker, explorer
globs: "*.py"
---
Rule instructions here...
```