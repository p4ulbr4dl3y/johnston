# Linters & Syntax Guards Reference

## Location
- Global linter config: `~/.johnston/linters.json`

## Presets Supported
- Python (`ruff`), JS/TS (`eslint`, `biome`), Rust (`rustc`), C/C++ (`gcc`), Ruby, PHP, JSON (`jq`), YAML (`yamllint`), TOML (`taplo`).

## Format
```json
{
  "linters": {
    "python": {
      "cmd": ["ruff", "check", "--select", "E9,F", "{file}"],
      "extensions": [".py"],
      "enabled": true
    }
  }
}
```

## Verification
- Run `johnston --linters` via shell tool to verify configured linters and system availability.