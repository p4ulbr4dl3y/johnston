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

## Transports
- **stdio**: Local subprocess via `command` + `args`.
- **sse / http**: Remote server via `url` (e.g. `https://example.com/mcp/sse`) + optional `headers`.

## Capabilities
- **Tools**: `tools/list` and `tools/call`.
- **Resources**: `resources/list` and `resources/read` (read directly via `read` tool with resource URI).
- **Prompts**: `prompts/list` and `prompts/get`.
- **Roots**: `roots/list` (automatically responds with project workspace).

## Verification
- Run `johnston --mcp` via shell tool to verify server registration and readiness.