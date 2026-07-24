try:
    from core.base_provider import BaseAgent
except ImportError:
    from base_provider import BaseAgent

NAME = "ClinePass"
KEY = "clinepass"
DESCRIPTION = "ClinePass custom AI provider"

BASE_URL = "https://api.cline.bot/api/v1"
MODEL = "cline-pass/deepseek-v4-flash"

MODELS = [
    "cline-pass/glm-5.2",
    "cline-pass/kimi-k3",
    "cline-pass/kimi-k2.7-code",
    "cline-pass/kimi-k2.6",
    "cline-pass/deepseek-v4-pro",
    "cline-pass/deepseek-v4-flash",
    "cline-pass/mimo-v2.5",
    "cline-pass/mimo-v2.5-pro",
    "cline-pass/minimax-m3",
    "cline-pass/qwen3.7-max",
    "cline-pass/qwen3.7-plus",
]


class Agent(BaseAgent):
    def __init__(self, api_key: str = "", model: str = MODEL, base_url: str = BASE_URL):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_key=KEY,
        )
