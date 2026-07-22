"""
OpenCode Go Provider configuration
"""
try:
    from core.base_provider import BaseAgent
except ImportError:
    from base_provider import BaseAgent

import os

NAME = "OpenCode Go"
KEY = "opencode"
DESCRIPTION = "OpenCode Go agent (DeepSeek v4 Flash) with tools"

BASE_URL = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4-flash"
API_KEY = os.getenv("OPENCODE_API_KEY", "")

try:
    from core.prompt_builder import DEFAULT_SYSTEM_PROMPT
    SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
except ImportError:
    SYSTEM_PROMPT = "You are Johnston, an expert AI software engineer."

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
