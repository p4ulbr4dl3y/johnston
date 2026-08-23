"""Default JSON provider configurations for Johnston CLI.

Users override these via ~/.johnston/providers.json: entries are merged
field-wise over the matching default, custom keys are added as-is, and
``"<key>": null`` removes a built-in default entirely. Enable/disable state
lives in config.json (``disabled_providers``), not here.
"""

from typing import Any, Dict

DEFAULT_JSON_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "key": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_type": "openai",
    },
    "anthropic": {
        "key": "anthropic",
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_type": "anthropic",
    },
    "gemini": {
        "key": "gemini",
        "name": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api_type": "gemini",
    },
    "openrouter": {
        "key": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_type": "openai",
    },
    "groq": {
        "key": "groq",
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_type": "openai",
    },
    "xai": {
        "key": "xai",
        "name": "xAI",
        "base_url": "https://api.x.ai/v1",
        "api_type": "openai",
    },
    "deepseek": {
        "key": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_type": "openai",
    },
    "mistral": {
        "key": "mistral",
        "name": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "api_type": "openai",
    },
    "togetherai": {
        "key": "togetherai",
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "api_type": "openai",
    },
    "deepinfra": {
        "key": "deepinfra",
        "name": "DeepInfra",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "api_type": "openai",
    },
    "fireworks": {
        "key": "fireworks",
        "name": "Fireworks",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_type": "openai",
    },
    "cerebras": {
        "key": "cerebras",
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "api_type": "openai",
    },
    "sambanova": {
        "key": "sambanova",
        "name": "SambaNova",
        "base_url": "https://api.sambanova.ai/v1",
        "api_type": "openai",
    },
    "nebius": {
        "key": "nebius",
        "name": "Nebius AI Studio",
        "base_url": "https://api.studio.nebius.ai/v1",
        "api_type": "openai",
    },
    "huggingface": {
        "key": "huggingface",
        "name": "Hugging Face",
        "base_url": "https://router.huggingface.co/novita/v1",
        "api_type": "openai",
    },
    "nvidia": {
        "key": "nvidia",
        "name": "Nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_type": "openai",
    },
    "moonshot": {
        "key": "moonshot",
        "name": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "api_type": "openai",
    },
    "zai": {
        "key": "zai",
        "name": "Zhipu AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_type": "openai",
    },
    "minimax": {
        "key": "minimax",
        "name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "api_type": "openai",
    },
    "lmstudio": {
        "key": "lmstudio",
        "name": "LM Studio",
        "base_url": "http://127.0.0.1:1234/v1",
        "api_type": "openai",
        "requires_key": False,
    },
    "litellm": {
        "key": "litellm",
        "name": "LiteLLM",
        "base_url": "http://localhost:4000/v1",
        "api_type": "openai",
        "requires_key": False,
    },
    "github-copilot": {
        "key": "github-copilot",
        "name": "GitHub Copilot",
        "base_url": "https://api.githubcopilot.com",
        "api_type": "openai",
    },
    "alibaba": {
        "key": "alibaba",
        "name": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_type": "openai",
    },
    "amazon-bedrock": {
        "key": "amazon-bedrock",
        "name": "Amazon Bedrock",
        "base_url": "https://bedrock-runtime.us-east-1.amazonaws.com",
        "api_type": "openai",
    },
    "azure": {
        "key": "azure",
        "name": "Azure OpenAI",
        "base_url": "https://{resource}.openai.azure.com/openai",
        "api_type": "openai",
    },
    "cloudflare-workers-ai": {
        "key": "cloudflare-workers-ai",
        "name": "Cloudflare Workers AI",
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "api_type": "openai",
    },
    "cohere": {
        "key": "cohere",
        "name": "Cohere",
        "base_url": "https://api.cohere.com/v2",
        "api_type": "openai",
    },
    "gitlab": {
        "key": "gitlab",
        "name": "GitLab Duo",
        "base_url": "https://gitlab.com/api/v4",
        "api_type": "openai",
    },
    "google-vertex": {
        "key": "google-vertex",
        "name": "Google Vertex AI",
        "base_url": "https://aiplatform.googleapis.com/v1",
        "api_type": "gemini",
    },
    "opencode": {
        "key": "opencode",
        "name": "OpenCode Zen",
        "base_url": "https://opencode.ai/zen/v1",
        "api_type": "openai",
    },
    "opencode-go": {
        "key": "opencode-go",
        "name": "OpenCode Go",
        "base_url": "https://opencode.ai/go/v1",
        "api_type": "openai",
    },
    "perplexity": {
        "key": "perplexity",
        "name": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "api_type": "openai",
    },
    "venice": {
        "key": "venice",
        "name": "Venice",
        "base_url": "https://api.venice.ai/api/v1",
        "api_type": "openai",
    },
    "vercel": {
        "key": "vercel",
        "name": "Vercel",
        "base_url": "https://ai.vercel.dev/v1",
        "api_type": "openai",
    },
}
