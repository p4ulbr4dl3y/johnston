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
    },
    "remote_sse": {
      "url": "https://mcp.example.com/sse",
      "headers": {
        "Authorization": "Bearer sse-secret-token"
      }
    }
  }
}
```

- **Stdio Transports**: `command` (string or list) is required; `args`, `env`, `cwd` are optional. `command`, `args`, and `env` support secret template substitution (`${SECRET_NAME}`).
- **SSE / HTTP Transports**: `url` is required (do not set `command`); `headers`, `env`, `cwd` are optional.
- `enabled` is optional. Active servers omit it; only `"enabled": false` is stored for disabled servers.

## Tool Namespacing & Collisions
- If an MCP tool name collides with a builtin tool or a tool from another MCP server, Johnston namespaces it as `<server_name>__<tool_name>`.
- Permissions and role filters are evaluated against the resolved namespaced name.

## Capabilities
- **Tools**: `tools/list` and `tools/call`.
- **Resources**: `resources/list` and `resources/read` (read directly via `read` tool with `resource://<uri>`).
- **Prompts**: `prompts/list` and `prompts/get` (executable in chat as `/<prompt>` or `/<server>__<prompt>`).
- **Roots**: `roots/list` (automatically responds with project workspace directory).

## Verification
- Run `johnston --mcp` via shell tool to verify server registration, readiness, and listed tools.