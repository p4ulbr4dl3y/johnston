"""
OpenRouter Provider configuration
"""
import os

from core.base_provider import BaseAgent
from core.prompt_builder import DEFAULT_SYSTEM_PROMPT
from tools.registry import get_default_tools

NAME = "OpenRouter"
KEY = "openrouter"
DESCRIPTION = "OpenRouter multi-model AI agent with tools"

BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/o3-mini"
API_KEY = os.getenv("OPENROUTER_API_KEY", "")

SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT
TOOLS = get_default_tools()


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
