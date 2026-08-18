# LLM Providers Configuration Reference

## Location
- Global provider config: `~/.johnston/providers.json`

## Supported API Types
- `openai` (OpenAI, OpenRouter, Groq, xAI, DeepSeek, custom OpenAI-compatible endpoints) — default, most presets.
- `anthropic` (Anthropic Claude API)
- `gemini` (Google Gemini REST API)
- Spec-cases handled in code (no dedicated preset): `ollama` and `lmstudio` (local backends, no API key required).

## Config.json Keys (`~/.johnston/config.json`)
- `api_keys`: provider API keys (managed via the in-app `/providers` screen), not environment variables. `johnston --models` only lists providers/models.
- `active_provider`: currently selected provider key.
- `provider_models`: per-provider chosen model (`{provider: model}`).
- `provider_thinking_efforts`: per-provider/per-model reasoning effort overrides.
- `disabled_providers`: list of disabled provider keys.