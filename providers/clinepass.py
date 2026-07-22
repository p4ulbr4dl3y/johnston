"""
ClinePass Provider configuration
"""
try:
    from core.base_provider import BaseAgent
except ImportError:
    from base_provider import BaseAgent

import os

NAME = "ClinePass"
KEY = "clinepass"
DESCRIPTION = "ClinePass AI provider (DeepSeek, GLM, Kimi, Qwen, MiniMax, MiMo)"

BASE_URL = "https://api.cline.bot/api/v1"
MODEL = "cline-pass/deepseek-v4-flash"
API_KEY = os.getenv("CLINEPASS_API_KEY", "")

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

try:
    from core.prompt_builder import DEFAULT_SYSTEM_PROMPT
    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
except ImportError:
    SYSTEM_PROMPT = "You write code."

try:
    from tools.registry import get_default_tools
    TOOLS = get_default_tools()
except ImportError:
    TOOLS = None


class Agent(BaseAgent):
    def __init__(self, api_key: str = API_KEY, model: str = MODEL, base_url: str = BASE_URL):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            system_prompt=SYSTEM_PROMPT,
            tools=TOOLS,
            provider_key=KEY
        )
