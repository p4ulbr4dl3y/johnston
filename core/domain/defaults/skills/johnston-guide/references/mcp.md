# MCP (Model Context Protocol) Server Configuration Reference

## Locations
- Global config: `~/.johnston/mcp.json`
- Project config: `.johnston/mcp.json`

## Config Format
```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": {},
      "disabled": false
    }
  }
}
```

## Transport
- **stdio** (via `command` + `args`) is the only executed transport.
- An optional `url` field is preserved in config, but HTTP/SSE URL transport is NOT yet executed — such servers are skipped.

## Verification
- Run `johnston --mcp` via shell tool to verify server registration and readiness.