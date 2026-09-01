# LLM Providers Configuration Reference

## Locations
- Global provider definitions: `~/.johnston/providers.json` (editable by agent)
- Centralized secrets: `~/.johnston/secrets.json` (blocked in sandbox mode)
- App configuration: `~/.johnston/config.json` (blocked in sandbox mode)

## Centralized Secrets (`~/.johnston/secrets.json`)
All API keys and tokens are stored in `~/.johnston/secrets.json` or provided via environment variables.
`providers.json` definitions can reference secrets via `${SECRET_NAME}` or `api_key: "${OPENAI_API_KEY}"`.
Resolution order: `~/.johnston/secrets.json` (exact) ➔ `os.environ` (exact) ➔ normalized variations (`<KEY>_API_KEY`, `<KEY>`, `<KEY>_TOKEN`).

## Supported API Types (`api_type`)
- `openai` (OpenAI, OpenRouter, Groq, xAI, DeepSeek, custom OpenAI-compatible endpoints) — default.
- `anthropic` (Anthropic Claude Messages API).
- `gemini` (Google Gemini REST API).
- Local/keyless: `ollama`, `lmstudio`, `litellm` (use `api_type: "openai"` + `requires_key: false`).

## Provider Schema (`~/.johnston/providers.json`)
```json
{
  "custom_openai": {
    "name": "Custom Endpoint",
    "api_type": "openai",
    "base_url": "https://api.example.com/v1",
    "api_key": "${CUSTOM_API_KEY}",
    "model": "gpt-4o",
    "models": ["gpt-4o", "gpt-4o-mini"],
    "fetch_models": true,
    "headers": {
      "X-Custom-Header": "value"
    },
    "extra_body": {},
    "reasoning_effort": "medium",
    "requires_key": true,
    "enabled": true,
    "chunk_timeout": 30.0,
    "max_tokens": 4096,
    "max_retries": 3,
    "retry_delay": 1.0
  },
  "disabled_default": null
}
```

- **Placeholder Substitution**: `base_url` supports placeholders like `{resource}` or `{account_id}` resolved from secrets/env.
- **Removing Defaults**: Set `"<provider_key>": null` to disable and hide a builtin provider.

## Model Selection & Config.json (`~/.johnston/config.json`)
- `model`: Single source of truth for provider and model (`"provider/model"` or bare `"provider"`).
- `llm.thinking_efforts`: Per-provider and per-model reasoning effort (`{"anthropic": {"claude-3-7-sonnet-latest": "medium"}}`).
- `permissions`: Execution mode and per-tool permission rules.