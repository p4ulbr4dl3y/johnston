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

- **Stdio Transports**: `command` (string or list) is required; `args`, `env`, `cwd` are optional. `command`, `args`, and `env` support variable interpolation (`${VAR}` and `$VAR`) resolved from `~/.johnston/secrets.json` and environment variables.
- **SSE / HTTP Transports**: `url` is required (do not set `command`); `headers`, `env`, `cwd` are optional.
- `enabled` is optional. Active servers omit it; only `"enabled": false` is stored for disabled servers.

## Tool Namespacing & Collisions
- If an MCP tool name collides with a builtin tool or a tool from another MCP server, Johnston namespaces it as `<server_name>__<tool_name>`.
- Permissions and role filters are evaluated against the resolved namespaced name.

## Capabilities
- **Tools**: `tools/list` and `tools/call`.
- **Resources**: `resources/list` and `resources/read`. Read directly via the `read` tool: any path containing a `://` scheme (e.g. `resource://<uri>`, `postgres://...`, `custom://...`) that does not exist on the local filesystem is intercepted and forwarded to MCP resources.
- **Prompts**: `prompts/list` and `prompts/get` (executable in chat as `/<prompt>` or `/<server>__<prompt>`).
- **Roots**: `roots/list` (automatically responds with project workspace directory).

## Verification & CLI Management (`johnston mcp`)
- `johnston mcp list [--json]`: Verify server registration, readiness, scope, and listed tools. Supports `--json` for structured JSON output.
- `johnston mcp add <name> (--cmd <cmd> | --url <url>) [--args ...] [--scope global|project]`: Add or update an MCP server definition.
- `johnston mcp rm <name> [--scope global|project]`: Remove an MCP server.
- `johnston mcp enable <name> [--scope global|project]`: Enable server.
- `johnston mcp disable <name> [--scope global|project]`: Disable server.
- Legacy verification: `johnston --mcp`.