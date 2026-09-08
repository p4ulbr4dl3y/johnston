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

## Built-in Providers (`DEFAULT_JSON_PROVIDERS`)
Johnston includes 34 preconfigured providers out of the box in `DEFAULT_JSON_PROVIDERS`:
- **General & Gateways**: `openai`, `anthropic`, `gemini`, `openrouter`, `groq`, `xai`, `deepseek`, `mistral`, `togetherai`, `deepinfra`, `fireworks`, `cerebras`, `sambanova`, `nebius`, `huggingface`, `nvidia`, `moonshot`, `zai`, `minimax`, `cohere`, `perplexity`, `venice`, `vercel`.
- **Cloud & Enterprise**: `alibaba`, `amazon-bedrock`, `azure`, `cloudflare-workers-ai`, `gitlab`, `google-vertex`, `github-copilot`.
- **Local & Specialized**: `lmstudio`, `litellm`, `opencode`, `opencode-go`.

Built-in providers can be enabled, disabled, customized, or removed in `~/.johnston/providers.json`. Setting `"<provider_key>": null` disables and hides a built-in provider entirely.

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
    "retry_delay": 1.0,
    "retry_backoff": 2.0,
    "max_retry_delay": 10.0
  },
  "disabled_default": null
}
```

## Base URL Placeholders
`base_url` supports template tokens such as `{resource}` (e.g. Azure OpenAI) and `{account_id}` (e.g. Cloudflare Workers AI).
Tokens are resolved in the following order:
1. Environment variable formatted as `<PROVIDER>_<TOKEN>` (e.g. `AZURE_RESOURCE`, `CLOUDFLARE_WORKERS_AI_ACCOUNT_ID`).
2. Exact token variable in `~/.johnston/secrets.json` or `os.environ` (e.g. `RESOURCE`, `ACCOUNT_ID`).
3. Matching string key in the provider dictionary.
Unresolved tokens remain verbatim with a warning logged pointing to the required environment variable.

## Thinking & Reasoning Effort
Reasoning models support configuring thinking effort levels:
- **Supported levels**: `low`, `medium`, `high`. Values `auto`, `none`, `unset`, or empty string reset or disable explicit thinking config.
- **Configuration locations**:
  - `~/.johnston/config.json` under `llm.thinking_efforts`: Per-provider and per-model mapping (e.g. `{"anthropic": {"claude-3-7-sonnet-latest": "medium"}}`).
  - `~/.johnston/providers.json`: Per-provider default (`"reasoning_effort": "medium"`).
  - CLI flag: `--effort low|medium|high`.
- **Provider-specific payload mapping**:
  - **OpenAI / compatible**: Passed as `reasoning_effort` (`"low"`, `"medium"`, `"high"`).
  - **Anthropic**: Passed as `output_config.effort` (`{"output_config": {"effort": "<level>"}}`).
  - **Gemini**:
    - Gemini 2.5 (`gemini-2.5*`): Translated to token budget via `thinkingBudget` (`low`: 1024, `medium`: 8192, `high`: 24576) with `"includeThoughts": true`.
    - Gemini 3 (`gemini-3*`): Translated to `{"thinkingLevel": "<level>"}`.

## Model Selection & Config.json (`~/.johnston/config.json`)
- `model`: Single source of truth for provider and model (`"provider/model"` or bare `"provider"`).
- `llm.thinking_efforts`: Per-provider and per-model reasoning effort.
- `permissions`: Execution mode and per-tool permission rules.

## CLI Provider Management (`johnston provider`)
Manage providers, API keys, and models from the command line:
- `johnston provider list [--json]`: Show table of configured providers, active models, key status (`[set]`, `[unset]`, `not required`), and state. Supports `--json` for structured JSON output.
- `johnston provider set-key <name> [key]`: Set provider API key. If key is omitted, prompts securely without terminal echo. If `-`, reads from stdin.
- `johnston provider set-model <name> <model>`: Set active model for provider.
- `johnston provider add <name> --model <model> [--api-key <k>] [--base-url <u>]`: Register a custom endpoint.
- `johnston provider rm <name>`: Remove custom provider profile from `providers.json`.
- `johnston provider enable <name>`: Enable a previously disabled provider.
- `johnston provider disable <name>`: Disable provider without deleting definition.