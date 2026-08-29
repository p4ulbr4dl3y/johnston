# LLM Providers Configuration Reference

## Locations
- Global provider definitions: `~/.johnston/providers.json` (editable by agent)
- Centralized secrets: `~/.johnston/secrets.json` (blocked in sandbox mode)
- App configuration: `~/.johnston/config.json` (blocked in sandbox mode)

## Centralized Secrets (`~/.johnston/secrets.json`)
All API keys and tokens are stored in `~/.johnston/secrets.json` or provided via environment variables.
`providers.json` definitions can reference secrets via `${SECRET_NAME}` or `api_key: "${OPENAI_API_KEY}"`.
Resolution order: `os.environ` ➔ `~/.johnston/secrets.json` ➔ `<PROVIDER>_API_KEY`.

## Supported API Types
- `openai` (OpenAI, OpenRouter, Groq, xAI, DeepSeek, custom OpenAI-compatible endpoints) — default.
- `anthropic` (Anthropic Claude API)
- `gemini` (Google Gemini REST API)
- Local/keyless: `ollama`, `lmstudio`, `litellm` (no API key required).

## Config.json Keys (`~/.johnston/config.json`)
- `active_provider`: currently selected provider key.
- `model`: selected model override (`provider/model` or `model`).
- `llm.thinking_efforts`: per-provider/per-model reasoning effort overrides.
- `permissions`: global tool and pattern execution permissions.