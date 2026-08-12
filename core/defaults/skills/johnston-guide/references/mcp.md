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

## Verification
- Run `johnston --mcp` via shell tool to verify server registration and readiness.