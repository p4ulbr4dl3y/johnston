# Johnston Tools Reference

## Builtin Tools
- `read`, `create`, `edit`, `shell`, `ask_user`
- `invoke_subagent`, `manage_subagent`, `manage_shell`, `update_plan`, `web_fetch`

## Permissions
- Global per-tool permissions stored in `~/.johnston/config.json` (`permissions.tools` section): `allow`, `ask`, or `deny` per tool, plus `permissions.default`.
- Session "always allow" overrides can be granted per tool during a session.