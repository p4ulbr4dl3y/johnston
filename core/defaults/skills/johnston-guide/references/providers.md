# LLM Providers Configuration Reference

## Location
- Global provider config: `~/.johnston/providers.json`

## Supported API Types
- `openai` (OpenAI, OpenRouter, Groq, xAI, DeepSeek, custom OpenAI-compatible endpoints)
- `anthropic` (Anthropic Claude API)
- `gemini` (Google Gemini REST API)
- `ollama` (local Ollama)

## API Keys
- Keys are stored in `~/.johnston/config.json` under `api_keys` (managed via `johnston --models`), not in environment variables.