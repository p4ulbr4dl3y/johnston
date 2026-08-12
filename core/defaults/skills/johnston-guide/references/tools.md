# Johnston Tools Reference

## Builtin Tools
- `read`, `create`, `edit`, `multi_edit`, `shell`, `ask_user`
- `invoke_subagent`, `manage_subagent`, `manage_shell`, `update_plan`, `web_fetch`
- Common aliases: `write_file` → `create`, `replace_file_content` → `edit`, `terminal`/`bash` → `shell`, `fetch` → `web_fetch`.

## Permissions
- Global per-tool permissions stored in `~/.johnston/config.json` (`permissions.tools` section): `allow`, `ask`, or `deny` per tool, plus `permissions.default`.
- Shell command guard (`permissions.shell_guard`) validates safety of commands run via `shell` tool.
- Session "always allow" overrides can be granted per tool during a session.