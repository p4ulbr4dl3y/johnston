# Rules & Directives Reference

## Locations
- Global rules: `~/.johnston/rules/<name>.md`
- Project rules: `.johnston/rules/<name>.md`
- Repository rules (auto-loaded from repo root): `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.windsurfrules`, `CONVENTIONS.md`.

## Frontmatter Format
```markdown
---
name: python_style
role: worker, explorer
---
Rule instructions here...
```

(Frontmatter fields supported: `name`; `role`/`roles`/`mode`/`modes` — comma-separated role whitelist. Unsupported/marketing fields such as `globs` are ignored.)