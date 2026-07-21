from typing import Any, Dict

class BaseTool:
    name: str = ""
    description: str = ""

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        raise NotImplementedError
