<div align="center"><pre>
   _       _                 _                 
  (_)     | |               | |                
   _  ___ | |__  _ __  ___ _| |_ ___  _ __     
  | |/ _ \| '_ \| '_ \/ __|_   _/ _ \| '_ \    
  | | (_) | | | | | | \__ \ | || (_) | | | |   
  | |\___/|_| |_|_| |_|___/  \__\___/|_| |_|   
 /_/                                           
    Python Terminal-based AI Assistant CLI
</pre></div>

## Quick Start

Run instantly:

```bash
uvx johnston
```

Install globally:

```bash
uv tool install johnston
```

Install via script:

```bash
curl -fsSL https://raw.githubusercontent.com/p4ulbr4dl3y/johnston/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/p4ulbr4dl3y/johnston/main/install.ps1 | iex
```

## Development

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run coverage run -m pytest
uv run coverage report -m

# Check code style
uv run ruff check .
```
