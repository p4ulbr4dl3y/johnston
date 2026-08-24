# MCP (Model Context Protocol) Server Configuration Reference

## Locations
- Global config: `~/.johnston/mcp.json` (editable by agent)
- Project config: `.johnston/mcp.json` (editable by agent)
- Secrets: `~/.johnston/secrets.json` (blocked in sandbox mode)

## Config Format
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

- `env`, `command`, `args` support secret template substitution (`${SECRET_NAME}`).
- `enabled` is optional. An enabled server simply omits it — only `"enabled": false` is stored for turned-off servers.
- `command` (string or list) is required; `args`, `env`, `cwd` are optional.

## Transport
- **stdio** (via `command` + `args`) is the only executed transport.
- An optional `url` field is preserved in config, but HTTP/SSE URL transport is NOT yet executed — such servers are skipped.

## Verification
- Run `johnston --mcp` via shell tool to verify server registration and readiness.