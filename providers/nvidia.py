"""
NVIDIA NIM Provider configuration
"""
import os

from core.base_provider import BaseAgent
from core.prompt_builder import DEFAULT_SYSTEM_PROMPT
from tools.registry import get_default_tools

NAME = "NVIDIA NIM"
KEY = "nvidia"
DESCRIPTION = "NVIDIA NIM multi-model AI agent with tools"

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "meta/codellama-70b"
API_KEY = os.getenv("NVIDIA_API_KEY", "")

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
